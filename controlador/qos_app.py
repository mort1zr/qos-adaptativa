"""
Aplicación Ryu del proyecto (historias PCIII-16: telemetría, PCIII-19: cada
flujo a su cola, y PCIII-20: clasificación por destino con reglas por adelantado).

Reemplaza a ryu.app.simple_switch_13. Arranque, desde ~/qos-adaptativa y con el
.venv activo (Python 3.9):

    ryu-manager controlador/qos_app.py

Qué hace:
  - Switches de segmento, islas e Internet: switch L2 que aprende direcciones
    MAC (igual que simple_switch_13).
  - Switches de acceso (acc0..acc4, el enlace de cada sede): con el PRIMER
    paquete de cada flujo IP (origen, destino, protocolo) el clasificador
    decide su clase, y se instala una regla OpenFlow con set_queue (la cola de
    esa clase) + salida. Los demás paquetes del flujo los despacha el switch
    sin consultar al controlador. La regla vence tras 'idle_timeout_s' sin
    tráfico. Cada decisión se guarda con su tiempo (tabla 'decisiones').
  - Cada 'intervalo_s' segundos pide las estadísticas de esas reglas y de los
    puertos y las guarda con controlador/telemetria.py en datos/telemetria.db.

Clasificadores (controlador/clasificadores.py):
  ninguno   sin set_queue: todo a la cola por defecto (sin_qos, fila_corta).
  politica  la clase que dice politicas/politicas.yaml sabiendo todo del destino.
  destino   tabla de destinos conocidos (estrategia prioridad). Además instala
            reglas POR ADELANTADO (proactivas) para esos destinos: el tráfico va
            a su cola desde el primer paquete, sin esperar al controlador, y una
            copia del primer paquete le llega al controlador solo para crear la
            regla por flujo que cuenta los bytes (la telemetría no se pierde).
El inicial está en controlador/telemetria.yaml ('clasificador'); se cambia en
caliente con la API REST, que solo escucha en esta máquina:

    curl http://127.0.0.1:8080/qos/estado
    curl -X PUT -d '{"nombre": "politica"}' http://127.0.0.1:8080/qos/clasificador

(o python3 controlador/api.py estado | clasificador politica). Al cambiar de
clasificador se borran las reglas por flujo, para que cada flujo se vuelva a
decidir con el nuevo.

El rol de cada switch lo lee de topologia/switches.csv, que escribe la
topología al construirse.
"""
import collections
import json
import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from ryu import cfg as ryu_cfg  # noqa: E402
from ryu.app.wsgi import ControllerBase, WSGIApplication, route  # noqa: E402
from ryu.base import app_manager  # noqa: E402
from ryu.controller import ofp_event  # noqa: E402
from ryu.controller.handler import (CONFIG_DISPATCHER, DEAD_DISPATCHER,  # noqa: E402
                                    MAIN_DISPATCHER, set_ev_cls)
from ryu.lib import hub  # noqa: E402
from ryu.lib.packet import ether_types, ethernet, ipv4, packet  # noqa: E402
from ryu.ofproto import ofproto_v1_3  # noqa: E402
from webob import Response  # noqa: E402

from controlador.clasificadores import CLASIFICADORES, armar_flujo, crear, red_para_openflow  # noqa: E402
from controlador.inventario import Inventario  # noqa: E402
from controlador.telemetria import Telemetria, leer_config, percentil  # noqa: E402
from politicas.cargador import cargar  # noqa: E402

COOKIE_FLUJO = 0x16          # reglas por flujo de esta aplicación (las de prueba de PCIII-15 usan 0x15)
COOKIE_PROACTIVA = 0x20      # reglas por adelantado (PCIII-20)
PRIORIDAD_FLUJO = 10
PRIORIDAD_PROACTIVA = 8
COPIA_BYTES = 128            # de la copia al controlador basta con las cabeceras
RECIENTE_S = 2.0             # no reinstalar la misma regla por flujo dentro de este tiempo
PRIORIDAD_ARP = 5
PRIORIDAD_L2 = 1
API = "qos_app"

# La API REST solo escucha en esta máquina (Ryu, por defecto, abre 0.0.0.0:8080).
# En una red real la API "hacia el norte" del controlador va además autenticada.
try:
    ryu_cfg.CONF.set_default("wsapi_host", "127.0.0.1")
except Exception:            # opción no registrada: se usa la de Ryu
    pass


class QoSApp(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cfg = leer_config()
        self.inv = Inventario()
        self.pol = cargar()
        self.tel = Telemetria(self.inv, self.pol, self.cfg["base_datos"],
                              intervalo_s=self.cfg["intervalo_s"],
                              retencion_h=self.cfg["retencion_flujos_h"])
        self.clasificador = crear(self.cfg["clasificador"], self.pol)
        self.mac_a_puerto = {}
        self.datapaths = {}
        self._partes = {}            # dpid -> estadísticas de flujos recibidas en varias partes
        self._decisiones = []        # se guardan en la base en cada sondeo
        self._ms = collections.deque(maxlen=2000)
        self._recientes = {}         # (dpid, in_port, origen, destino, proto) -> ts de la regla instalada
        self.proactivas = {}         # dpid -> reglas por adelantado instaladas
        self.contadores = {"packet_in": 0, "packet_in_acceso": 0, "decisiones": 0,
                           "cambios_clasificador": 0}
        kwargs["wsgi"].register(QoSRest, {API: self})
        self.logger.info("QoSApp: clasificador '%s', telemetría cada %s s en %s (%d equipos, "
                         "%d switches de acceso); API en http://127.0.0.1:%s/qos/estado",
                         self.clasificador.nombre, self.cfg["intervalo_s"], self.cfg["base_datos"],
                         len(self.inv.por_ip), len(self.inv.accesos()),
                         getattr(ryu_cfg.CONF, "wsapi_port", 8080))
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

    def acciones_flujo(self, dp, cola, salida):
        """Acciones de la regla de un flujo: su cola (set_queue) y la salida.
        Sin clasificador no se marca la cola: todo va a la cola por defecto."""
        parser = dp.ofproto_parser
        if self.clasificador.nombre == "ninguno":
            return [parser.OFPActionOutput(salida)]
        return [parser.OFPActionSetQueue(cola), parser.OFPActionOutput(salida)]

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
            n = self._instalar_proactivas(dp, sw)
            self.logger.info("Switch de acceso %s (sede %s) conectado%s", sw["nombre"], sw["sede_id"],
                             f"; {n} reglas por adelantado" if n else "")

    def _instalar_proactivas(self, dp, sw):
        """Reglas por adelantado del clasificador para los destinos conocidos, en los dos
        sentidos. Llevan su cola y una copia del paquete al controlador (solo las
        cabeceras), para que la regla por flujo de la telemetría se cree igual."""
        ofp, parser = dp.ofproto, dp.ofproto_parser
        reglas = self.clasificador.reglas_proactivas(list(self.inv.por_ip.values()), sw["sede_id"])
        for r in reglas:
            cola = self.pol.cola(r.clase)
            for entra, origen, destino in ((sw["puerto_sede"], r.local, r.remota),
                                           (sw["puerto_operador"], r.remota, r.local)):
                match = parser.OFPMatch(in_port=entra, eth_type=ether_types.ETH_TYPE_IP,
                                        ipv4_src=red_para_openflow(origen), ipv4_dst=red_para_openflow(destino))
                acciones = [parser.OFPActionSetQueue(cola),
                            parser.OFPActionOutput(self.otro_puerto(sw, entra)),
                            parser.OFPActionOutput(ofp.OFPP_CONTROLLER, COPIA_BYTES)]
                self.agregar_flujo(dp, PRIORIDAD_PROACTIVA, match, acciones, cookie=COOKIE_PROACTIVA)
        self.proactivas[dp.id] = 2 * len(reglas)
        return 2 * len(reglas)

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
        t0 = time.perf_counter()
        msg = ev.msg
        dp = msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        in_port = msg.match["in_port"]
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        self.contadores["packet_in"] += 1

        sw = self.inv.switch(dp.id)
        if sw and sw["tipo"] == "acceso" and sw["puerto_operador"] and sw["puerto_sede"]:
            salida = self.otro_puerto(sw, in_port)
            ip = pkt.get_protocol(ipv4.ipv4)
            if ip:
                self.contadores["packet_in_acceso"] += 1
                # Copia de una regla por adelantado: el paquete YA salió por su cola;
                # solo falta la regla por flujo que cuenta sus bytes.
                copia = msg.reason == ofp.OFPR_ACTION
                flujo = armar_flujo(self.inv, sw, ip.src, ip.dst, ip.proto, in_port)
                decision = self.clasificador.clasificar(flujo)
                cola = self.pol.cola(decision.clase)
                acciones = self.acciones_flujo(dp, cola, salida)
                clave = (dp.id, in_port, ip.src, ip.dst, ip.proto)
                nueva = time.time() - self._recientes.get(clave, 0) > RECIENTE_S
                if nueva:
                    self._recientes[clave] = time.time()
                    match = parser.OFPMatch(in_port=in_port, eth_type=ether_types.ETH_TYPE_IP,
                                            ipv4_src=ip.src, ipv4_dst=ip.dst, ip_proto=ip.proto)
                    buffer_id = None if copia else msg.buffer_id
                    self.agregar_flujo(dp, PRIORIDAD_FLUJO, match, acciones,
                                       idle=self.cfg["idle_timeout_s"], cookie=COOKIE_FLUJO,
                                       flags=ofp.OFPFF_SEND_FLOW_REM, buffer_id=buffer_id)
                    if not copia and msg.buffer_id != ofp.OFP_NO_BUFFER:
                        self._anotar(dp.id, flujo, decision, cola, (time.perf_counter() - t0) * 1000, "reactiva")
                        return
                if not copia:
                    datos = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
                    dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
                                                    actions=acciones, data=datos))
                if nueva:
                    self._anotar(dp.id, flujo, decision, cola, (time.perf_counter() - t0) * 1000,
                                 "proactiva" if copia else "reactiva")
                return
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

    def _anotar(self, dpid, flujo, decision, cola, ms, via):
        self.contadores["decisiones"] += 1
        self._ms.append(ms)
        local = flujo.local
        o, d = self.inv.equipo(flujo.origen_ip), self.inv.equipo(flujo.destino_ip)
        self._decisiones.append({
            "ts": flujo.ts, "dpid": dpid, "sede_id": flujo.sede_id, "sentido": flujo.sentido,
            "origen_ip": flujo.origen_ip, "destino_ip": flujo.destino_ip, "proto": flujo.proto,
            "origen": o["nombre"] if o else flujo.origen_ip, "destino": d["nombre"] if d else flujo.destino_ip,
            "area": local["area"] if local else "Desconocida", "clasificador": self.clasificador.nombre,
            "clase": decision.clase, "cola": cola, "motivo": decision.motivo, "ms": round(ms, 3),
            "servicio": decision.servicio, "via": via})

    # ---------------- clasificador (API) ----------------
    def poner_clasificador(self, nombre):
        """Cambia el clasificador y borra las reglas por flujo de los switches de acceso:
        cada flujo se vuelve a decidir con el nuevo en su siguiente paquete."""
        self.clasificador = crear(nombre, self.pol)
        self.contadores["cambios_clasificador"] += 1
        self._recientes.clear()
        self.inv.recargar()
        borrados = 0
        for dpid, dp in list(self.datapaths.items()):
            sw = self.inv.switch(dpid)
            if sw and sw["tipo"] == "acceso":
                ofp, parser = dp.ofproto, dp.ofproto_parser
                for cookie in (COOKIE_FLUJO, COOKIE_PROACTIVA):
                    dp.send_msg(parser.OFPFlowMod(datapath=dp, command=ofp.OFPFC_DELETE,
                                                  table_id=ofp.OFPTT_ALL, cookie=cookie,
                                                  cookie_mask=0xFFFFFFFFFFFFFFFF, out_port=ofp.OFPP_ANY,
                                                  out_group=ofp.OFPG_ANY, match=parser.OFPMatch()))
                dp.send_msg(parser.OFPBarrierRequest(dp))      # borrar antes de instalar las nuevas
                self._instalar_proactivas(dp, sw)
                borrados += 1
        self.logger.info("Clasificador -> '%s' (reglas borradas y reinstaladas en %d switches de acceso; "
                         "%d reglas por adelantado)", nombre, borrados, sum(self.proactivas.values()))
        return borrados

    def estado(self):
        ms = list(self._ms)
        return {
            "clasificador": self.clasificador.nombre,
            "clasificadores": {n: c.descripcion for n, c in CLASIFICADORES.items()},
            "switches_acceso": sorted(self.inv.switch(d)["nombre"] for d in self.datapaths
                                      if self.inv.es_acceso(d)),
            "contadores": dict(self.contadores),
            "decision_ms": {"n": len(ms), "p50": percentil(ms, 50), "p95": percentil(ms, 95),
                            "max": max(ms) if ms else None},
            "idle_timeout_s": self.cfg["idle_timeout_s"],
            "reglas_por_adelantado": {self.inv.switch(d)["nombre"]: n for d, n in self.proactivas.items()
                                      if d in self.datapaths and self.inv.switch(d)},
        }

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
                pendientes, self._decisiones = self._decisiones, []
                self.tel.registrar_decisiones(pendientes)
                viejas = time.time() - RECIENTE_S
                self._recientes = {k: v for k, v in self._recientes.items() if v > viejas}
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


def _json(obj, estado=200):
    return Response(status=estado, content_type="application/json", charset="utf-8",
                    body=json.dumps(obj, ensure_ascii=False).encode("utf-8"))


class QoSRest(ControllerBase):
    """API REST local del controlador (lo que en SDN se llama la interfaz "norte")."""

    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self.app = data[API]

    @route("qos", "/qos/estado", methods=["GET"])
    def estado(self, req, **kwargs):
        return _json(self.app.estado())

    @route("qos", "/qos/clasificador", methods=["PUT", "POST"])
    def clasificador(self, req, **kwargs):
        try:
            nombre = json.loads(req.body.decode("utf-8") or "{}").get("nombre")
        except (ValueError, AttributeError):
            return _json({"error": "se esperaba JSON: {\"nombre\": \"politica\"}"}, 400)
        if nombre not in CLASIFICADORES:
            return _json({"error": f"clasificador desconocido: {nombre}",
                          "clasificadores": list(CLASIFICADORES)}, 400)
        self.app.poner_clasificador(nombre)
        return _json(self.app.estado())
