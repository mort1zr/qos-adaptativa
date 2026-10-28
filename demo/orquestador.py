#!/usr/bin/env python3
"""Coordina la demo desde una API local de acciones fijas."""
import argparse
import collections
import csv
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import yaml

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
from controlador.topologia import leer_progreso  # noqa: E402
from escenarios.escenario import devolver_al_usuario, cargar_escenarios  # noqa: E402

ACTIVOS = {"iniciando", "corriendo"}
RUTAS_QOS = {"/qos/estado", "/qos/telemetria", "/qos/serie", "/qos/topologia", "/qos/progreso"}


class ErrorDemo(Exception):
    def __init__(self, mensaje, codigo=400):
        super().__init__(mensaje)
        self.codigo = codigo


def validar_escenario(cuerpo, cfg, escenarios):
    campos = {"nombre", "estrategias", "sala", "rapido"}
    if not isinstance(cuerpo, dict) or set(cuerpo) != campos:
        raise ErrorDemo("Indica nombre, estrategias, sala y rapido, sin campos adicionales.")
    nombre, estrategias, sala = cuerpo["nombre"], cuerpo["estrategias"], cuerpo["sala"]
    if not isinstance(nombre, str) or nombre not in escenarios:
        raise ErrorDemo("Escenario desconocido. Elige uno de la lista.")
    if (not isinstance(estrategias, list) or len(estrategias) not in (1, 2)
            or any(not isinstance(e, str) or e not in cfg["estrategias"] for e in estrategias)
            or len(set(estrategias)) != len(estrategias)):
        raise ErrorDemo("Elige una o dos estrategias distintas de la lista.")
    if type(sala) is not int or sala not in cfg["salas"] or type(cuerpo["rapido"]) is not bool:
        raise ErrorDemo("Sala o velocidad inválida.")
    return dict(cuerpo)


def comando_escenario(cuerpo, cfg):
    return [sys.executable, "-u", "escenarios/escenario.py", "--nombre", cuerpo["nombre"],
            "--estrategia", ",".join(cuerpo["estrategias"]), "--sala", str(cuerpo["sala"]),
            "--escala", str(cfg["escala_rapida"] if cuerpo["rapido"] else 1),
            "--datapath", cfg["datapath"], "--salida", cfg["resultados_demo"],
            "--progreso", "datos/progreso.json"]


def comandos_controlador(cfg, iniciar):
    modo = cfg["controlador"]
    if modo == "lab":
        return ["docker", "start" if iniciar else "stop", "qos-controlador-lab"]
    if modo == "docker":
        return ["docker", "compose", "up", "-d"] if iniciar else ["docker", "compose", "down"]
    if not iniciar:
        return None
    usuario = os.environ.get("SUDO_USER")
    if not usuario or usuario == "root":
        raise ErrorDemo("En modo venv inicia con sudo desde tu usuario normal.")
    return ["sudo", "-u", usuario, str(RAIZ / cfg["venv"]), "--wsapi-host", "127.0.0.1",
            "controlador/qos_app.py"]


def comandos_evidencia(tipo, sala):
    tabla = {
        "switches": ([["ovs-vsctl", "show"], ["ovs-vsctl", "--columns=target,is_connected", "list", "Controller"]],
                     "Los bridges acc son los accesos de las sedes. is_connected indica la conexión con Ryu."),
        "reglas": ([["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", "acc%d" % sala]],
                   "set_queue:N envía el flujo a una cola. 0x16 identifica reglas por flujo y 0x20 reglas anticipadas."),
        "colas": ([["tc", "-s", "class", "show", "dev", "acc%d-eth%d" % (sala, n)] for n in (2, 1)],
                  "Primero bajada y después subida. Sent cuenta bytes; dropped cuenta paquetes descartados."),
        "qos": ([["ovs-vsctl", "list", "QoS"]], "linux-htb distribuye el ancho de banda entre las colas.")}
    if tipo not in tabla:
        raise ErrorDemo("Tipo de evidencia desconocido.")
    return tabla[tipo]


class Demo:
    ESPERA_REINICIO_S = 8      # tiempo que se espera a que Docker reviva el controlador tras `mn -c`

    def __init__(self, raiz=RAIZ, ejecutar=subprocess.run, lanzar=subprocess.Popen, vista_previa=False,
                 api_url="http://127.0.0.1:8080", controlador=None):
        self.api_url = api_url
        self.raiz, self.ejecutar, self.lanzar = Path(raiz).resolve(), ejecutar, lanzar
        self.vista_previa = vista_previa
        self.cfg = yaml.safe_load((self.raiz / "demo/demo.yaml").read_text())
        if controlador is not None:
            self.cfg["controlador"] = controlador
        if self.cfg["controlador"] not in {"lab", "venv", "docker"} or self.cfg["datapath"] not in {"kernel", "user"}:
            raise ValueError("Revisa controlador y datapath en demo/demo.yaml")
        salida = (self.raiz / self.cfg["resultados_demo"]).resolve()
        if salida.parent != self.raiz / "experimentos/resultados" or not salida.name.startswith("demo") or salida.suffix != ".csv":
            raise ValueError("Los resultados de demo deben ir a experimentos/resultados/demo*.csv")
        if not 0 < self.cfg["escala_rapida"] <= 1:
            raise ValueError("escala_rapida debe estar entre 0 y 1")
        if (not isinstance(self.cfg["salas"], list) or
                any(type(s) is not int or s not in (1, 2, 3, 4) for s in self.cfg["salas"]) or
                not self.cfg["salas"] or not set(self.cfg["estrategias"]) <= {"sin_qos", "fila_corta", "prioridad", "estatica"}):
            raise ValueError("Revisa salas y estrategias en demo/demo.yaml")
        self.escenarios = cargar_escenarios()["escenarios"]
        self.lock, self.accion_lock, self.log_lock = threading.RLock(), threading.Lock(), threading.Lock()
        self.trabajo = {"tipo": None, "estado": "inactivo"}
        self.proceso = self.ryu = None
        self.red_lista = False
        self.logs, self.numero = collections.deque(maxlen=500), 0
        self.ultimo_error = None

    def log(self, linea):
        with self.log_lock:
            self.numero += 1
            self.logs.append({"n": self.numero, "texto": linea.rstrip()[:4096]})
            carpeta = self.raiz / "datos"
            carpeta.mkdir(exist_ok=True)
            ruta = carpeta / "demo.log"
            if ruta.exists() and ruta.stat().st_size > 1024 * 1024:
                os.replace(str(ruta), str(carpeta / "demo.log.1"))
            with ruta.open("a") as f:
                f.write(linea.rstrip()[:4096] + "\n")
            devolver_al_usuario(str(ruta))

    def run(self, comando, timeout=30):
        try:
            r = self.ejecutar(comando, cwd=str(self.raiz), capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ErrorDemo("No se pudo ejecutar %s: %s" % (comando[0], e), 500)
        if r.returncode:
            raise ErrorDemo((r.stderr or r.stdout or "La acción falló")[-4096:], 500)
        return r.stdout

    def api_activa(self):
        try:
            with urllib.request.urlopen(self.api_url + "/qos/estado", timeout=1) as r:
                return r.status == 200
        except (OSError, ValueError):
            return False

    def activo(self):
        return self.trabajo["estado"] in ACTIVOS

    def estado(self):
        api = self.api_activa()
        with self.lock:
            try:
                with (self.raiz / "topologia/switches.csv").open() as f:
                    esperados = sum(1 for _ in csv.DictReader(f))
            except OSError:
                esperados = 0
            return {"vista_previa": self.vista_previa,
                    "controlador": {"estado": "corriendo" if api else "apagado", "api": api,
                                    "modo": self.cfg["controlador"], "pid": self.ryu.pid if self.ryu else None},
                    "red": {"estado": ("corriendo" if self.red_lista else "iniciando")
                            if self.activo() else "apagado", "switches_esperados": esperados},
                    "trabajo": dict(self.trabajo), "ultimo_error": self.ultimo_error,
                    **leer_progreso(self.raiz / "datos"),
                    "opciones": {"salas": self.cfg["salas"], "estrategias": self.cfg["estrategias"],
                                 "escala_rapida": self.cfg["escala_rapida"]}}

    def vigilar(self, proc, trabajo=None):
        for linea in proc.stdout:
            self.log(linea)
            if trabajo is not None and "*** Red lista" in linea:
                with self.lock:
                    self.red_lista = True
                    trabajo["estado"] = "corriendo"
        codigo = proc.wait()
        if trabajo is not None:
            with self.lock:
                if trabajo.get("cancelando"):
                    trabajo["estado"] = "cancelado"
                else:
                    trabajo["estado"] = "terminado" if codigo == 0 else "fallido"
                trabajo["codigo"] = codigo
                self.red_lista = False
                if codigo and not trabajo.get("cancelando"):
                    self.ultimo_error = "El trabajo falló. Revisa el registro y usa «Limpiar todo»."
                if self.proceso is proc:
                    self.proceso = None
            self.devolver_archivos()

    def devolver_archivos(self):
        for carpeta in ("datos", "topologia", "experimentos/resultados"):
            for ruta in (self.raiz / carpeta).rglob("*"):
                if not ruta.is_symlink():
                    devolver_al_usuario(str(ruta))

    def empezar(self, tipo, comando, parametros):
        if self.activo():
            raise ErrorDemo("Hay otro trabajo en curso. Espera o cancélalo.", 409)
        try:
            proc = self.lanzar(comando, cwd=str(self.raiz), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, start_new_session=True)
        except OSError as e:
            raise ErrorDemo("No se pudo iniciar el trabajo: %s" % e, 500)
        with self.lock:
            self.trabajo = {"tipo": tipo, "estado": "corriendo" if tipo == "escenario" else "iniciando",
                            "inicio": time.time(), "parametros": parametros}
            self.red_lista = False
            self.proceso = proc
            trabajo = self.trabajo
        threading.Thread(target=self.vigilar, args=(proc, trabajo), daemon=True).start()

    def controlador(self, iniciar):
        if not iniciar and self.activo():
            raise ErrorDemo("Detén el trabajo antes de apagar el controlador.", 409)
        if iniciar and self.api_activa():
            raise ErrorDemo("El controlador ya está encendido.", 409)
        if iniciar:
            for puerto in (6633, 6653, 8080):
                with socket.socket() as s:
                    if s.connect_ex(("127.0.0.1", puerto)) == 0:
                        try:
                            detalle = self.run(["ss", "-ltnp", "sport = :%d" % puerto], 3)
                        except ErrorDemo:
                            detalle = ""
                        raise ErrorDemo("El puerto %d está ocupado. Detén el controlador anterior. %s" % (puerto, detalle), 409)
        cmd = comandos_controlador(self.cfg, iniciar)
        if self.cfg["controlador"] == "venv":
            if iniciar:
                if self.ryu is not None and self.ryu.poll() is None:
                    raise ErrorDemo("Ryu todavía está iniciando.", 409)
                try:
                    self.ryu = self.lanzar(cmd, cwd=str(self.raiz), stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, text=True, start_new_session=True)
                except OSError as e:
                    raise ErrorDemo("Revisa el entorno de Ryu: %s" % e, 500)
                threading.Thread(target=self.vigilar, args=(self.ryu,), daemon=True).start()
            elif self.ryu is not None:
                self.terminar_proceso(self.ryu)
                self.ryu = None
            elif self.api_activa():
                raise ErrorDemo("Este Ryu fue iniciado fuera de la consola. Deténlo desde su terminal.", 409)
        else:
            if self.cfg["controlador"] == "lab" and iniciar:
                try:
                    self.run(["docker", "inspect", "qos-controlador-lab"])
                except ErrorDemo:
                    raise ErrorDemo("No hay despliegue del pipeline. Usa modo venv o docker en demo.yaml.", 409)
            self.run(cmd)
        if iniciar:
            for _ in range(20):
                if self.api_activa():
                    return
                time.sleep(0.5)
            raise ErrorDemo("Ryu no respondió. Revisa sus dependencias y el registro.", 500)

    @staticmethod
    def terminar_proceso(proc):
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=20)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)

    def cancelar(self):
        with self.lock:
            proc = self.proceso
            trabajo = self.trabajo
            if proc is None:
                return
            trabajo["cancelando"] = True
        self.terminar_proceso(proc)
        # No permitir que una limpieza vieja alcance una red nueva.
        try:
            self.limpiar(propia=True)
        finally:
            with self.lock:
                trabajo["estado"] = "cancelado"
                self.red_lista = False
                if self.proceso is proc:
                    self.proceso = None
            progreso = leer_progreso(self.raiz / "datos")["progreso"]
            if trabajo["tipo"] == "escenario" and progreso:
                from escenarios.progreso import Progreso
                p = Progreso(self.raiz / "datos/progreso.json")
                p.datos = progreso
                p.finalizar("cancelado", "Cancelado desde la consola")

    def verificar_red_externa(self):
        try:
            r = self.ejecutar(["pgrep", "-f", "^bash --norc --noediting -is mininet:"],
                              capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            raise ErrorDemo("No se pudo verificar si hay otra red de Mininet. Revisa pgrep.", 500)
        if r.returncode == 0:
            raise ErrorDemo("Hay una red de Mininet fuera de esta consola. Deténla antes de continuar.", 409)
        if r.returncode != 1:
            raise ErrorDemo("No se pudo comprobar el estado de Mininet.", 500)

    def limpiar(self, propia=False):
        if not propia:
            self.verificar_red_externa()
        encendido = self.api_activa()
        self.run(["mn", "-c"], timeout=30)
        try:
            if encendido:
                self.recuperar_controlador()
        finally:
            self.devolver_archivos()

    def recuperar_controlador(self):
        """`mn -c` ejecuta `killall ryu-manager` como root y, desde el host, también ve los
        procesos de un contenedor: el controlador puede caer en cualquier modo, no solo en venv.
        En modo Docker se le da unos segundos a `restart: unless-stopped`; si no vuelve
        (o es venv, que no se revive solo), se arranca de nuevo."""
        espera = 0 if self.cfg["controlador"] == "venv" else self.ESPERA_REINICIO_S
        limite = time.monotonic() + espera
        while True:
            if self.api_activa():
                return
            if time.monotonic() >= limite:
                break
            time.sleep(0.5)
        self.log("*** Limpiar apagó el controlador: se inicia de nuevo")
        self.controlador(True)

    def actuar(self, ruta, cuerpo):
        if self.vista_previa:
            raise ErrorDemo("Vista previa: no se ejecutan acciones de red. Inicia con sudo para la demo real.", 409)
        if not self.accion_lock.acquire(blocking=False):
            raise ErrorDemo("Hay una acción en curso. Espera a que termine.", 409)
        try:
            return self._actuar(ruta, cuerpo)
        finally:
            self.accion_lock.release()

    def _actuar(self, ruta, cuerpo):
        if ruta == "/demo/escenario":
            cuerpo = validar_escenario(cuerpo, self.cfg, self.escenarios)
        elif ruta == "/demo/red/iniciar":
            if cuerpo != {"estrategia": "colas"}:
                raise ErrorDemo("La red en reposo usa estrategia colas.")
        elif cuerpo != {}:
            raise ErrorDemo("Esta acción no admite parámetros.")
        if ruta.startswith("/demo/controlador/"):
            if ruta not in {"/demo/controlador/iniciar", "/demo/controlador/detener"}:
                raise ErrorDemo("Acción desconocida.", 404)
            self.controlador(ruta.endswith("/iniciar"))
        elif ruta in {"/demo/cancelar", "/demo/red/detener", "/demo/limpiar"}:
            if ruta == "/demo/red/detener" and self.activo() and self.trabajo["tipo"] != "red":
                raise ErrorDemo("Usa Cancelar para detener el escenario.", 409)
            if self.activo():
                self.cancelar()
            elif ruta == "/demo/limpiar":
                self.limpiar()
        elif ruta in {"/demo/escenario", "/demo/red/iniciar"}:
            if not self.api_activa():
                raise ErrorDemo("Primero inicia el controlador.", 409)
            if self.activo():
                if ruta == "/demo/escenario" and self.trabajo["tipo"] == "red":
                    self.cancelar()
                else:
                    raise ErrorDemo("Hay otro trabajo en curso.", 409)
            self.verificar_red_externa()
            if ruta == "/demo/escenario":
                # Evitar mostrar una corrida anterior mientras se prepara la nueva.
                from escenarios.progreso import Progreso
                p = Progreso(self.raiz / "datos/progreso.json")
                p.datos = {"version": 1, "estado": "iniciando", "corridas": [], "error": None}
                p.guardar()
                self.empezar("escenario", comando_escenario(cuerpo, self.cfg), cuerpo)
            else:
                self.empezar("red", [sys.executable, "-u", "topologia/empresa_xyz.py", "--sin-cli",
                                     "--esperar", "--estrategia", "colas", "--datapath", self.cfg["datapath"]], cuerpo)
        else:
            raise ErrorDemo("Acción desconocida.", 404)
        self.ultimo_error = None
        return {"mensaje": "Acción completada"}

    def evidencia(self, tipo, sala):
        if type(sala) is not int or sala not in [0] + self.cfg["salas"]:
            raise ErrorDemo("Sala inválida.")
        comandos, explicacion = comandos_evidencia(tipo, sala)
        if not self.activo() or not self.red_lista and self.trabajo["tipo"] == "red":
            raise ErrorDemo("Levanta la red primero.", 409)
        salida = ""
        for c in comandos:
            texto = self.run(c, timeout=5)
            if tipo == "switches" and c == ["ovs-vsctl", "show"]:
                lineas, incluir = [], True
                for linea in texto.splitlines():
                    if linea.lstrip().startswith("Bridge "):
                        incluir = linea.strip().split()[-1].strip('"') in {"acc%d" % n for n in range(5)}
                    if incluir:
                        lineas.append(linea)
                texto = "\n".join(lineas)
            salida += "$ " + " ".join(c) + "\n" + texto + "\n"
        if len(salida.encode()) > 65536:
            salida = salida.encode()[:65000].decode(errors="replace") + "\n[Salida recortada a 64 kB]"
        return {"tipo": tipo, "sala": sala, "comando": " / ".join(" ".join(c) for c in comandos),
                "salida": salida, "explicacion": explicacion}


def crear_handler(demo):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def responder(self, datos, codigo=200, tipo="application/json; charset=utf-8"):
            contenido = datos if isinstance(datos, bytes) else json.dumps(datos, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(contenido)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-src 'self'")
            self.end_headers()
            self.wfile.write(contenido)

        def local(self):
            host = self.headers.get("Host", "")
            esperados = {"127.0.0.1:%d" % self.server.server_port, "localhost:%d" % self.server.server_port}
            if host not in esperados:
                raise ErrorDemo("Acceso permitido únicamente desde localhost.", 403)
            origen = self.headers.get("Origin")
            if origen is not None and origen != "http://" + host:
                raise ErrorDemo("Origen de la solicitud no permitido.", 403)

        def cuerpo(self):
            if self.headers.get_content_type() != "application/json":
                raise ErrorDemo("Envía application/json.", 415)
            longitud = int(self.headers.get("Content-Length", "0"))
            if not 0 < longitud <= 16384:
                raise ErrorDemo("Cuerpo vacío o demasiado grande.")
            contenido = json.loads(self.rfile.read(longitud))
            if not isinstance(contenido, dict):
                raise ErrorDemo("Se esperaba un objeto JSON.")
            return contenido

        def proxy(self, cuerpo=None):
            if self.command == "GET":
                return self._proxy(cuerpo)
            if not demo.accion_lock.acquire(blocking=False):
                raise ErrorDemo("Hay una acción en curso.", 409)
            try:
                return self._proxy(cuerpo)
            finally:
                demo.accion_lock.release()

        def _proxy(self, cuerpo=None):
            partes = urlsplit(self.path)
            permitidas = RUTAS_QOS if self.command == "GET" else {"/qos/clasificador"}
            if partes.path not in permitidas:
                raise ErrorDemo("Ruta no disponible.", 404)
            if self.command != "GET":
                if demo.vista_previa or demo.activo() and demo.trabajo["tipo"] == "escenario":
                    raise ErrorDemo("El escenario controla el clasificador o la vista es de solo lectura.", 409)
                if set(cuerpo) != {"nombre"} or cuerpo["nombre"] not in ("ninguno", "politica", "destino"):
                    raise ErrorDemo("Clasificador inválido.")
            peticion = urllib.request.Request(demo.api_url + self.path,
                                             data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                             headers={"Content-Type": "application/json"}, method=self.command)
            try:
                with urllib.request.urlopen(peticion, timeout=3) as r:
                    self.responder(r.read(), r.status, r.headers.get("Content-Type", "application/json"))
            except urllib.error.HTTPError as e:
                self.responder(e.read(), e.code)
            except OSError:
                raise ErrorDemo("El controlador está apagado.", 503)

        def despachar(self):
            try:
                self.local()
                partes = urlsplit(self.path)
                ruta, query = partes.path, parse_qs(partes.query)
                if self.command == "GET":
                    if ruta == "/":
                        return self.responder((demo.raiz / "demo/consola/index.html").read_bytes(), tipo="text/html; charset=utf-8")
                    if ruta == "/panel":
                        return self.responder((demo.raiz / "controlador/panel/index.html").read_bytes(), tipo="text/html; charset=utf-8")
                    if ruta == "/demo/estado":
                        return self.responder(demo.estado())
                    if ruta == "/demo/escenarios":
                        return self.responder({"escenarios": [{"nombre": n, **e} for n, e in demo.escenarios.items()]})
                    if ruta == "/demo/log":
                        desde = int(query.get("desde", [0])[0])
                        with demo.log_lock:
                            return self.responder({"lineas": [l for l in demo.logs if l["n"] > desde], "ultimo": demo.numero})
                    if ruta.startswith("/demo/evidencia/"):
                        return self.responder(demo.evidencia(ruta.rsplit("/", 1)[1], int(query.get("sala", [1])[0])))
                    if ruta.startswith("/qos/"):
                        return self.proxy()
                elif self.command in {"POST", "PUT"}:
                    cuerpo = self.cuerpo()
                    if self.command == "PUT" and ruta.startswith("/qos/"):
                        return self.proxy(cuerpo)
                    if self.command == "POST":
                        return self.responder(demo.actuar(ruta, cuerpo))
                raise ErrorDemo("Ruta no disponible.", 404)
            except ErrorDemo as e:
                self.responder({"error": str(e)}, e.codigo)
            except (ValueError, TypeError):
                self.responder({"error": "Parámetros o JSON inválidos."}, 400)
            except (OSError, RuntimeError) as e:
                demo.ultimo_error = str(e)
                self.responder({"error": "La acción falló: %s" % e}, 500)

        do_GET = despachar
        do_POST = despachar
        do_PUT = despachar
    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vista-previa", action="store_true", help="solo interfaz, sin acciones ni privilegios")
    p.add_argument("--controlador", choices=("lab", "venv", "docker"),
                   help="usar este modo sin modificar demo.yaml")
    args = p.parse_args()
    if os.geteuid() != 0 and not args.vista_previa:
        sys.exit("Inicia con sudo python3 demo/orquestador.py, o usa --vista-previa para revisar la interfaz.")
    demo = Demo(vista_previa=args.vista_previa, controlador=args.controlador)
    servidor = ThreadingHTTPServer(("127.0.0.1", 8090), crear_handler(demo))

    def detener(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, detener)
    print("Consola en http://127.0.0.1:8090" + (" (vista previa)" if args.vista_previa else ""), flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        if demo.activo():
            demo.cancelar()
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
