#!/usr/bin/env python3
"""
Topología de la Empresa XYZ en Mininet: oficina central + 4 salas conectadas
a la red de un mismo operador.

Uso (con sudo y el Python del sistema, NO el del .venv):
  sudo python3 topologia/empresa_xyz.py                    # con Ryu (arrancarlo antes)
  sudo python3 topologia/empresa_xyz.py --verificar        # ping desde la oficina a todo
  sudo python3 topologia/empresa_xyz.py --sin-controlador  # prueba sin Ryu

Diseño:
  - Cada sede tiene un router Linux y un switch OVS por segmento (VLAN).
    Las tragamonedas se reparten en "islas", cada una con su switch.
  - Cada sede se conecta al router del operador (rop) por su enlace de acceso.
    Ese enlace pasa por un switch OVS propio (acc0..acc4) cuyos dos puertos
    llevan una cola HTB: limita la capacidad en ambos sentidos. Ahí aplicará
    la QoS el sistema en los siguientes sprints.
  - El operador también da salida a Internet (servidores 203.0.113.0/24).
  - El retardo se aplica con netem en las interfaces de los routers, nunca en
    los puertos OVS, para no pisar las colas HTB.
"""
import argparse
import csv
import os
import socket
import subprocess
import sys
from collections import OrderedDict

import yaml
from mininet.cli import CLI
from mininet.log import error, info, setLogLevel
from mininet.net import Mininet
from mininet.node import Node, OVSSwitch, RemoteController

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG_DEFECTO = os.path.join(AQUI, "empresa_xyz.yaml")
INVENTARIO = os.path.join(AQUI, "inventario.csv")

# segmento -> (octeto de red, código corto para nombres de switch/interfaz)
SEGMENTOS = {
    "servidores":     (10, "ser"),
    "maquinas":       (10, "maq"),
    "administracion": (20, "adm"),
    "pagos":          (30, "pag"),
    "cctv":           (40, "cct"),
    "wifi_personal":  (50, "wfp"),
    "wifi_clientes":  (60, "wfc"),
}


class Router(Node):
    """Host Linux que enruta entre sus interfaces."""

    def config(self, **params):
        super().config(**params)
        self.cmd("sysctl -qw net.ipv4.ip_forward=1")

    def terminate(self):
        self.cmd("sysctl -qw net.ipv4.ip_forward=0")
        super().terminate()


def controlador_activo(ip="127.0.0.1", puerto=6633):
    """True si hay un controlador escuchando (por ejemplo, Ryu)."""
    try:
        with socket.create_connection((ip, puerto), timeout=2):
            return True
    except OSError:
        return False


AVISO_RYU = ("No hay controlador en {ip}:{puerto}.\n"
             "  1. Si acabas de ejecutar 'sudo mn -c', recuerda que eso también apaga Ryu.\n"
             "  2. Arranca Ryu en otra terminal (con el .venv activo):\n"
             "       ryu-manager ryu.app.simple_switch_13\n"
             "  3. Vuelve a ejecutar este comando.\n"
             "  (O agrega --sin-controlador para probar sin Ryu.)")


def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        error(f"*** Falló: {cmd}\n{r.stderr}\n")
    return r


class EmpresaXYZ:
    def __init__(self, cfg, controlador=True, ip_ctrl="127.0.0.1", puerto_ctrl=6633):
        self.cfg = cfg
        self.net = Mininet(controller=None, switch=OVSSwitch, build=False)
        self.fail_mode = "secure" if controlador else "standalone"
        self.n_dpid = 0
        self.inventario = []
        self.puertos_acceso = []   # (switch, puerto, mbps, sentido)
        self.retardos = []         # (router, interfaz, ms)
        self.routers = {}
        if controlador:
            self.net.addController("c0", controller=RemoteController,
                                   ip=ip_ctrl, port=puerto_ctrl)

    # ---------------- piezas básicas ----------------
    def switch(self, nombre):
        # DPID explícito: Mininet lo deduciría del nombre y habría choques.
        self.n_dpid += 1
        return self.net.addSwitch(nombre, dpid=f"{self.n_dpid:016x}",
                                  protocols="OpenFlow13", failMode=self.fail_mode)

    def router(self, nombre):
        r = self.net.addHost(nombre, cls=Router, ip=None)
        self.routers[nombre] = r
        return r

    def segmento(self, router, sid, prefijo, sede, nombre):
        """Crea el switch del segmento, lo une al router y devuelve su contexto."""
        octeto, corto = SEGMENTOS[nombre]
        base = f"10.{sid}.{octeto}"
        sw = self.switch(f"sw{sid}{corto}")
        self.net.addLink(router, sw, intfName1=f"{router.name}-{corto}",
                         params1={"ip": f"{base}.1/24"})
        return {"sw": sw, "base": base, "n": 0, "sid": sid, "sede": sede,
                "seg": nombre, "corto": corto, "prefijo": prefijo}

    def equipo(self, ctx, alias, tipo, sw=None, detalle=""):
        nombre = f"{ctx['prefijo']}{alias}"
        ip = f"{ctx['base']}.{10 + ctx['n']}"
        ctx["n"] += 1
        h = self.net.addHost(nombre, ip=f"{ip}/24", defaultRoute=f"via {ctx['base']}.1")
        self.net.addLink(h, sw or ctx["sw"])
        self.inventario.append({
            "nombre": nombre, "sede_id": ctx["sid"], "sede": ctx["sede"],
            "segmento": ctx["seg"], "tipo": tipo, "ip": ip,
            "gateway": f"{ctx['base']}.1", "detalle": detalle,
        })

    def acceso(self, sid, r_sede, rop, mbps, ms):
        """Enlace de acceso sede <-> operador, con su switch acc<sid>."""
        sw = self.switch(f"acc{sid}")
        l_op = self.net.addLink(rop, sw, intfName1=f"rop-s{sid}",
                                params1={"ip": f"172.16.{sid}.1/30"})
        l_se = self.net.addLink(r_sede, sw, intfName1=f"r{sid}-acc",
                                params1={"ip": f"172.16.{sid}.2/30"})
        # Puerto hacia el operador = subida de la sede; hacia la sede = bajada.
        self.puertos_acceso.append((sw.name, l_op.intf2.name, mbps, "subida"))
        self.puertos_acceso.append((sw.name, l_se.intf2.name, mbps, "bajada"))
        self.retardos.append((rop, f"rop-s{sid}", ms))
        self.retardos.append((r_sede, f"r{sid}-acc", ms))

    # ---------------- sedes ----------------
    def oficina(self, rop):
        ofi = self.cfg["oficina"]
        r0 = self.router("r0")
        for nombre_seg, equipos in ofi["segmentos"].items():
            ctx = self.segmento(r0, 0, "of", ofi["nombre"], nombre_seg)
            for alias, tipo in equipos:
                self.equipo(ctx, alias, tipo)
        cctv = self.segmento(r0, 0, "of", ofi["nombre"], "cctv")
        self.equipo(cctv, "nvr", "nvr")
        for i in range(1, ofi["camaras"] + 1):
            self.equipo(cctv, f"cam{i:02d}", "camara_ip")
        self.acceso(0, r0, rop, ofi["enlace"]["mbps"], ofi["enlace"]["retardo_ms"])

    def sala(self, s, rop):
        sid, nombre = s["id"], s["nombre"]
        p = f"sa{sid}"
        r = self.router(f"r{sid}")

        # Máquinas: servidor de sala, derby y ruleta en el switch principal;
        # tragamonedas repartidas en islas.
        maq = self.segmento(r, sid, p, nombre, "maquinas")
        self.equipo(maq, "srv", "servidor_sala")
        for i in range(1, s["derby"] + 1):
            self.equipo(maq, "derby" if s["derby"] == 1 else f"derby{i}", "derby")
        for i in range(1, s["ruleta"] + 1):
            self.equipo(maq, "ruleta" if s["ruleta"] == 1 else f"rul{i}", "ruleta")
        islas = []
        for k in range(1, s["islas"] + 1):
            isw = self.switch(f"sw{sid}is{k}")
            self.net.addLink(maq["sw"], isw)
            islas.append(isw)
        for i in range(s["tragamonedas"]):
            k = i * s["islas"] // s["tragamonedas"]   # reparto equilibrado
            self.equipo(maq, f"tm{i + 1:02d}", "tragamonedas",
                        sw=islas[k], detalle=f"isla {k + 1}")

        adm = self.segmento(r, sid, p, nombre, "administracion")
        for alias, tipo in self.cfg["plantilla_sala"]["administracion"]:
            self.equipo(adm, alias, tipo)

        pag = self.segmento(r, sid, p, nombre, "pagos")
        for i in range(1, s["pos"] + 1):
            self.equipo(pag, f"pos{i}", "pos")

        cct = self.segmento(r, sid, p, nombre, "cctv")
        self.equipo(cct, "nvr", "nvr")
        for i in range(1, s["camaras"] + 1):
            self.equipo(cct, f"cam{i:02d}", "camara_ip")

        # Los 2 access points sirven ambas redes WiFi; se anotan en "detalle".
        wfp = self.segmento(r, sid, p, nombre, "wifi_personal")
        for i in range(1, s["celulares_personal"] + 1):
            self.equipo(wfp, f"cel{i}", "celular", detalle=f"AP{(i - 1) % 2 + 1}")
        wfc = self.segmento(r, sid, p, nombre, "wifi_clientes")
        for i in range(1, s["clientes_wifi"] + 1):
            self.equipo(wfc, f"cli{i}", "cliente_wifi", detalle=f"AP{(i - 1) % 2 + 1}")

        self.acceso(sid, r, rop, s["enlace"]["mbps"], s["enlace"]["retardo_ms"])

    def internet(self, rop):
        sw = self.switch("swinet")
        self.net.addLink(rop, sw, intfName1="rop-inet", params1={"ip": "203.0.113.1/24"})
        for s in self.cfg["internet"]["servidores"]:
            h = self.net.addHost(s["nombre"], ip=f"{s['ip']}/24",
                                 defaultRoute="via 203.0.113.1")
            self.net.addLink(h, sw)
            self.inventario.append({
                "nombre": s["nombre"], "sede_id": "inet", "sede": "Internet",
                "segmento": "internet", "tipo": s["servicio"], "ip": s["ip"],
                "gateway": "203.0.113.1", "detalle": "",
            })

    def construir(self):
        rop = self.router("rop")   # red del operador
        self.oficina(rop)
        for s in self.cfg["salas"]:
            self.sala(s, rop)
        self.internet(rop)

    # ---------------- configuración tras arrancar ----------------
    def configurar(self, firewall=False):
        # Sin IPv6: evita la ráfaga de mensajes automáticos (descubrimiento de
        # vecinos) que satura al controlador al arrancar y ensucia las mediciones.
        for h in self.net.hosts:
            h.cmd("sysctl -qw net.ipv6.conf.all.disable_ipv6=1 "
                  "net.ipv6.conf.default.disable_ipv6=1")
        rop = self.routers["rop"]
        sedes = [0] + [s["id"] for s in self.cfg["salas"]]
        for sid in sedes:
            rop.cmd(f"ip route add 10.{sid}.0.0/16 via 172.16.{sid}.2")
            self.routers[f"r{sid}"].cmd(f"ip route add default via 172.16.{sid}.1")

        for r, intf, ms in self.retardos:
            r.cmd(f"tc qdisc replace dev {intf} root netem delay {ms}ms")

        # Línea base "sin QoS": una sola cola que solo limita la capacidad.
        for _, puerto, mbps, _ in self.puertos_acceso:
            bps = int(mbps * 1_000_000)
            sh(f"ovs-vsctl -- set port {puerto} qos=@q "
               f"-- --id=@q create qos type=linux-htb other-config:max-rate={bps} queues:0=@q0 "
               f"-- --id=@q0 create queue other-config:min-rate={bps} other-config:max-rate={bps}")

        if firewall:
            # Desde Internet solo entran respuestas a conexiones iniciadas desde dentro.
            rop.cmd("iptables -A FORWARD -i rop-inet -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT")
            rop.cmd("iptables -A FORWARD -i rop-inet -d 10.0.0.0/8 -j DROP")

        with open(INVENTARIO, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(self.inventario[0].keys()))
            w.writeheader()
            w.writerows(self.inventario)

    def resumen(self):
        info(f"\n*** {self.cfg['empresa']}: {len(self.inventario)} equipos, "
             f"{len(self.routers)} routers, {len(self.net.switches)} switches OVS\n")
        por_sede = OrderedDict()
        for f in self.inventario:
            por_sede[f["sede"]] = por_sede.get(f["sede"], 0) + 1
        for sede, n in por_sede.items():
            info(f"    {sede:22s} {n:4d} equipos\n")
        info("*** Enlaces de acceso (cola HTB única = línea base sin QoS)\n")
        for sw, puerto, mbps, sentido in self.puertos_acceso:
            info(f"    {sw:5s} {puerto:10s} {mbps:>3} Mbps {sentido}\n")
        info(f"*** Inventario: {INVENTARIO}\n")

    def verificar(self, origen="ofsis1"):
        """Ping desde una PC de la oficina a todos los equipos, en paralelo por segmento."""
        h0 = self.net.get(origen)
        info(f"\n*** Verificando conectividad desde {origen} ({h0.IP()})\n")
        grupos = OrderedDict()
        for f in self.inventario:
            if f["nombre"] != origen:
                grupos.setdefault((f["sede"], f["segmento"]), []).append(f)

        fallas, total = [], 0
        info(f"\n    {'Sede':22s} {'Segmento':15s} {'Alcanzables':>12s}  RTT prom\n")
        for (sede, seg), filas in grupos.items():
            ips = " ".join(f["ip"] for f in filas)
            out = h0.cmd(
                f"for ip in {ips}; do "
                f"(r=$(ping -c2 -i0.2 -W2 $ip | tail -1); echo \"RES $ip|$r\") & "
                f"done; wait")
            res = {}
            for linea in out.splitlines():
                if linea.startswith("RES "):
                    ip, _, r = linea[4:].partition("|")
                    res[ip] = float(r.split("=")[1].split("/")[1]) if "=" in r else None
            ok = [res[f["ip"]] for f in filas if res.get(f["ip"]) is not None]
            fallas += [f for f in filas if res.get(f["ip"]) is None]
            total += len(filas)
            rtt = f"{sum(ok) / len(ok):6.1f} ms" if ok else "   -"
            info(f"    {sede:22s} {seg:15s} {len(ok):>5d}/{len(filas):<5d}  {rtt}\n")

        info(f"\n*** Resultado: {total - len(fallas)}/{total} equipos alcanzables\n")
        for f in fallas:
            info(f"    FALLA: {f['nombre']} ({f['ip']}) {f['sede']} / {f['segmento']}\n")
        return not fallas

    def limpiar(self):
        for _, puerto, _, _ in self.puertos_acceso:
            sh(f"ovs-vsctl --if-exists clear port {puerto} qos")
        sh("ovs-vsctl -- --all destroy QoS -- --all destroy Queue")


def main():
    p = argparse.ArgumentParser(description="Topología de la Empresa XYZ")
    p.add_argument("--config", default=CONFIG_DEFECTO)
    p.add_argument("--verificar", action="store_true", help="ping a todos los equipos al iniciar")
    p.add_argument("--sin-cli", action="store_true", help="no abrir la consola de Mininet")
    p.add_argument("--sin-controlador", action="store_true",
                   help="switches autónomos (sin Ryu), útil para depurar")
    p.add_argument("--firewall", action="store_true",
                   help="bloquea conexiones iniciadas desde Internet")
    p.add_argument("--ip-controlador", default="127.0.0.1")
    p.add_argument("--puerto-controlador", type=int, default=6633)
    args = p.parse_args()

    if os.geteuid() != 0:
        sys.exit("Ejecuta con sudo: sudo python3 topologia/empresa_xyz.py")

    if not args.sin_controlador and not controlador_activo(args.ip_controlador,
                                                           args.puerto_controlador):
        sys.exit(AVISO_RYU.format(ip=args.ip_controlador, puerto=args.puerto_controlador))

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    setLogLevel("info")
    emp = EmpresaXYZ(cfg, controlador=not args.sin_controlador,
                     ip_ctrl=args.ip_controlador, puerto_ctrl=args.puerto_controlador)
    emp.construir()
    emp.net.start()
    try:
        emp.configurar(firewall=args.firewall)
        emp.resumen()
        if args.verificar:
            emp.verificar()
        if not args.sin_cli:
            info("*** Aviso: no uses 'pingall' (son ~280 equipos); usa --verificar\n")
            CLI(emp.net)
    finally:
        emp.limpiar()
        emp.net.stop()


if __name__ == "__main__":
    main()
