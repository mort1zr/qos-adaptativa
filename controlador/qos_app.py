"""
Aplicación Ryu del proyecto (historia PCIII-16: telemetría).

Reemplaza a ryu.app.simple_switch_13. Arranque, desde ~/qos-adaptativa y con el
.venv activo (Python 3.9):

    ryu-manager controlador/qos_app.py

Qué hace:
  - Switches de segmento, islas e Internet: switch L2 que aprende direcciones
    MAC (igual que simple_switch_13).
  - Switches de acceso (acc0..acc4, el enlace de cada sede): una regla OpenFlow
    por flujo IP (origen, destino, protocolo) con contadores propios. Cada
    'intervalo_s' segundos pide las estadísticas de esos flujos y de los puertos,
    y las guarda con controlador/telemetria.py en datos/telemetria.db.
    Cuando un flujo vence (idle_timeout), el switch avisa y se guardan sus
    últimos bytes. En el Sprint 3 esas mismas reglas llevarán set_queue.

El rol de cada switch lo lee de topologia/switches.csv, que escribe la
topología al construirse. Configuración: controlador/telemetria.yaml.
Consultas: python3 controlador/consultas.py demanda --area Contabilidad --minutos 10
"""
import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from ryu.base import app_manager  # noqa: E402
from ryu.controller import ofp_event  # noqa: E402
from ryu.controller.handler import (CONFIG_DISPATCHER, DEAD_DISPATCHER,  # noqa: E402
                                    MAIN_DISPATCHER, set_ev_cls)
from ryu.lib import hub  # noqa: E402
from ryu.lib.packet import ether_types, ethernet, ipv4, packet  # noqa: E402
from ryu.ofproto import ofproto_v1_3  # noqa: E402

from controlador.inventario import Inventario  # noqa: E402
from controlador.telemetria import Telemetria, leer_config  # noqa: E402
from politicas.cargador import cargar  # noqa: E402

COOKIE_FLUJO = 0x16          # reglas por flujo de esta aplicación (las de prueba de PCIII-15 usan 0x15)
PRIORIDAD_FLUJO = 10
PRIORIDAD_ARP = 5
PRIORIDAD_L2 = 1


class QoSApp(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cfg = leer_config()
        self.inv = Inventario()
        self.pol = cargar()
        self.tel = Telemetria(self.inv, self.pol, self.cfg["base_datos"],
                              intervalo_s=self.cfg["intervalo_s"],
                              retencion_h=self.cfg["retencion_flujos_h"])
        self.mac_a_puerto = {}
        self.datapaths = {}
        self._partes = {}            # dpid -> estadísticas de flujos recibidas en varias partes
        self.logger.info("QoSApp: telemetría cada %s s en %s (%d equipos, %d switches de acceso)",
                         self.cfg["intervalo_s"], self.cfg["base_datos"], len(self.inv.por_ip),
                         len(self.inv.accesos()))
        self.hilo = hub.spawn(self._sondear)

    # ---------------- utilidades ----------------
    @staticmethod
    def agregar_flujo(dp, prioridad, match, acciones, idle=0, cookie=0, flags=0, buffer_id=None):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, acciones)]
        extra = {"buffer_id": buffer_id} if buffer_id not in (None, ofp.OFP_NO_BUFFER) else {}
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=prioridad, match=match, instructions=inst,
                                      idle_timeout=idle, cookie=cookie, flags=flags, **extra))

    @staticmethod
    def otro_puerto(sw, in_port):
        """En un switch de acceso, lo que entra por un lado sale por el otro."""
        return sw["puerto_sede"] if in_port == sw["puerto_operador"] else sw["puerto_operador"]

    def acciones_flujo(self, dp, sw, ip, salida):
        """Acciones de la regla de un flujo. En el Sprint 3 se agregará set_queue aquí."""
        return [dp.ofproto_parser.OFPActionOutput(salida)]

    # ---------------- conexión de los switches ----------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def al_conectar(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        self.inv.recargar()
        # Lo que no tenga regla, al controlador.
        self.agregar_flujo(dp, 0, parser.OFPMatch(),
                           [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)])
        sw = self.inv.switch(dp.id)
        if sw and sw["tipo"] == "acceso":
            for entra in (sw["puerto_operador"], sw["puerto_sede"]):
                self.agregar_flujo(dp, PRIORIDAD_ARP,
                                   parser.OFPMatch(in_port=entra, eth_type=ether_types.ETH_TYPE_ARP),
                                   [parser.OFPActionOutput(self.otro_puerto(sw, entra))])
            self.logger.info("Switch de acceso %s (sede %s) conectado", sw["nombre"], sw["sede_id"])

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def al_cambiar_estado(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dp.id, None)

    # ---------------- reenvío ----------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def al_recibir_paquete(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        in_port = msg.match["in_port"]
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        sw = self.inv.switch(dp.id)
        if sw and sw["tipo"] == "acceso" and sw["puerto_operador"] and sw["puerto_sede"]:
            salida = self.otro_puerto(sw, in_port)
            ip = pkt.get_protocol(ipv4.ipv4)
            if ip:
                match = parser.OFPMatch(in_port=in_port, eth_type=ether_types.ETH_TYPE_IP,
                                        ipv4_src=ip.src, ipv4_dst=ip.dst, ip_proto=ip.proto)
                acciones = self.acciones_flujo(dp, sw, ip, salida)
                self.agregar_flujo(dp, PRIORIDAD_FLUJO, match, acciones,
                                   idle=self.cfg["idle_timeout_s"], cookie=COOKIE_FLUJO,
                                   flags=ofp.OFPFF_SEND_FLOW_REM, buffer_id=msg.buffer_id)
                if msg.buffer_id != ofp.OFP_NO_BUFFER:
                    return
            else:
                acciones = [parser.OFPActionOutput(salida)]
        else:
            # Switch L2 con aprendizaje de MAC (como simple_switch_13).
            tabla = self.mac_a_puerto.setdefault(dp.id, {})
            tabla[eth.src] = in_port
            salida = tabla.get(eth.dst, ofp.OFPP_FLOOD)
            acciones = [parser.OFPActionOutput(salida)]
            if salida != ofp.OFPP_FLOOD:
                match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst, eth_src=eth.src)
                self.agregar_flujo(dp, PRIORIDAD_L2, match, acciones, buffer_id=msg.buffer_id)
                if msg.buffer_id != ofp.OFP_NO_BUFFER:
                    return

        datos = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
                                        actions=acciones, data=datos))

    # ---------------- telemetría ----------------
    def _sondear(self):
        vueltas = 0
        while True:
            hub.sleep(self.cfg["intervalo_s"])
            try:
                self.inv.recargar()
                for dpid, dp in list(self.datapaths.items()):
                    if self.inv.es_acceso(dpid):
                        self._pedir_estadisticas(dp)
                vueltas += 1
                if vueltas % 720 == 0:          # ~ cada hora con 5 s
                    borradas = self.tel.limpiar()
                    if borradas:
                        self.logger.info("Telemetría: %d filas por flujo antiguas borradas", borradas)
            except Exception:                    # el sondeo nunca debe morir
                self.logger.exception("Error en el sondeo de telemetría")

    def _pedir_estadisticas(self, dp):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        dp.send_msg(parser.OFPFlowStatsRequest(dp, 0, ofp.OFPTT_ALL, ofp.OFPP_ANY, ofp.OFPG_ANY,
                                               COOKIE_FLUJO, 0xFFFFFFFFFFFFFFFF, parser.OFPMatch()))
        dp.send_msg(parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY))

    @staticmethod
    def _muestra(st):
        m = st.match
        return {"origen_ip": m.get("ipv4_src"), "destino_ip": m.get("ipv4_dst"),
                "proto": m.get("ip_proto"), "in_port": m.get("in_port"),
                "bytes": st.byte_count, "paquetes": st.packet_count,
                "duracion_s": st.duration_sec + st.duration_nsec / 1e9}

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def al_recibir_flujos(self, ev):
        msg = ev.msg
        dpid = msg.datapath.id
        self._partes.setdefault(dpid, []).extend(
            st for st in msg.body if st.cookie == COOKIE_FLUJO and "ipv4_src" in st.match)
        if msg.flags & msg.datapath.ofproto.OFPMPF_REPLY_MORE:
            return                               # faltan partes de la respuesta
        estadisticas = self._partes.pop(dpid, [])
        try:
            self.tel.registrar_flujos(dpid, [self._muestra(st) for st in estadisticas], ts=time.time())
        except Exception:
            self.logger.exception("Error al guardar la telemetría de flujos")

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def al_recibir_puertos(self, ev):
        puertos = [{"port_no": p.port_no, "tx_bytes": p.tx_bytes, "tx_packets": p.tx_packets,
                    "tx_dropped": p.tx_dropped} for p in ev.msg.body]
        try:
            self.tel.registrar_puertos(ev.msg.datapath.id, puertos, ts=time.time())
        except Exception:
            self.logger.exception("Error al guardar la telemetría de puertos")

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def al_vencer_flujo(self, ev):
        msg = ev.msg
        if msg.cookie != COOKIE_FLUJO or "ipv4_src" not in msg.match:
            return
        try:
            self.tel.registrar_flujos(msg.datapath.id, [self._muestra(msg)], ts=time.time(),
                                      eliminados=True)
        except Exception:
            self.logger.exception("Error al guardar un flujo vencido")
