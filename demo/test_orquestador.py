"""Pruebas de acciones, estados y HTTP sin root ni Mininet."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from demo.orquestador import (RAIZ, Demo, ErrorDemo, comandos_controlador, comandos_evidencia,
                              comando_escenario, crear_handler, validar_escenario)


class Acciones(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        (self.raiz / "demo").mkdir()
        (self.raiz / "experimentos/resultados").mkdir(parents=True)
        shutil.copy(RAIZ / "demo/demo.yaml", self.raiz / "demo/demo.yaml")
        self.run = Mock(return_value=subprocess.CompletedProcess([], 1, "", ""))
        self.demo = Demo(self.raiz, ejecutar=self.run, lanzar=Mock())
        self.datos = {"nombre": "enlace_degradado", "estrategias": ["prioridad"], "sala": 1, "rapido": True}

    def test_escenario_valido_comando_sin_shell(self):
        cuerpo = validar_escenario(self.datos, self.demo.cfg, self.demo.escenarios)
        cmd = comando_escenario(cuerpo, self.demo.cfg)
        self.assertIn("--progreso", cmd)
        self.assertEqual(cmd[cmd.index("--salida") + 1], "experimentos/resultados/demo.csv")
        self.assertEqual(cmd[cmd.index("--escala") + 1], "0.5")

    def test_lista_blanca(self):
        for extra in ({"nombre": "x; touch /tmp/error"}, {"sala": 9}, {"sala": True},
                      {"estrategias": ["prioridad", "sin_qos", "estatica"]},
                      {"estrategias": ["prioridad", "prioridad"]}, {"estrategias": [["ia"]]},
                      {"estrategias": ["ia"]}, {"rapido": "true"}, {"comando": "id"}):
            with self.subTest(extra=extra), self.assertRaises(ErrorDemo):
                validar_escenario({**self.datos, **extra}, self.demo.cfg, self.demo.escenarios)

    def test_no_inicia_red_con_escenario_activo(self):
        self.demo.api_activa = lambda: True
        self.demo.trabajo = {"tipo": "escenario", "estado": "corriendo"}
        with self.assertRaises(ErrorDemo) as error:
            self.demo.actuar("/demo/red/iniciar", {"estrategia": "colas"})
        self.assertEqual(error.exception.codigo, 409)
        self.demo.lanzar.assert_not_called()

    def test_no_apaga_controlador_con_red_activa(self):
        self.demo.trabajo = {"tipo": "red", "estado": "iniciando"}
        with self.assertRaises(ErrorDemo):
            self.demo.actuar("/demo/controlador/detener", {})
        self.run.assert_not_called()

    def test_no_inicia_sin_controlador(self):
        self.demo.api_activa = lambda: False
        with self.assertRaises(ErrorDemo):
            self.demo.actuar("/demo/escenario", self.datos)
        self.demo.lanzar.assert_not_called()

    def test_vista_previa_nunca_ejecuta(self):
        self.demo.vista_previa = True
        with self.assertRaises(ErrorDemo):
            self.demo.actuar("/demo/limpiar", {})
        self.run.assert_not_called()

    def test_comandos_de_controlador(self):
        self.assertEqual(comandos_controlador(self.demo.cfg, True), ["docker", "start", "qos-controlador-lab"])
        self.assertEqual(comandos_controlador({**self.demo.cfg, "controlador": "docker"}, False),
                         ["docker", "compose", "down"])
        with patch.dict("os.environ", {"SUDO_USER": "alumno"}):
            cmd = comandos_controlador({**self.demo.cfg, "controlador": "venv"}, True)
        self.assertEqual(cmd[:3], ["sudo", "-u", "alumno"])
        self.assertIn("127.0.0.1", cmd)

    def test_modo_local_no_modifica_configuracion(self):
        ruta = self.raiz / "demo/demo.yaml"
        original = ruta.read_bytes()
        demo = Demo(self.raiz, controlador="docker")
        self.assertEqual(demo.cfg["controlador"], "docker")
        self.assertEqual(ruta.read_bytes(), original)

    def test_evidencias_validacion_y_timeout(self):
        self.demo.trabajo = {"tipo": "red", "estado": "corriendo"}
        self.demo.red_lista = True
        self.run.return_value = subprocess.CompletedProcess([], 0, "class htb 1:1", "")
        self.assertIn("bajada", self.demo.evidencia("colas", 1)["explicacion"])
        self.assertEqual(self.run.call_args.kwargs["timeout"], 5)
        for tipo, sala in (("reglas", 9), ("id", 1), ("colas", True)):
            with self.assertRaises(ErrorDemo):
                self.demo.evidencia(tipo, sala)
        self.assertIn("--columns=target,is_connected", comandos_evidencia("switches", 0)[0][1])

    def test_rechaza_otra_red_al_limpiar(self):
        self.run.return_value = subprocess.CompletedProcess([], 0, "123\n", "")
        with self.assertRaises(ErrorDemo):
            self.demo.limpiar()
        self.assertEqual(len(self.run.call_args_list), 1)

    def test_vigilar_proceso_y_registro_acotado(self):
        proc = Mock(stdout=io.StringIO("*** Red lista\n"))
        proc.wait.return_value = 0
        trabajo = {"tipo": "red", "estado": "iniciando"}
        self.demo.proceso = proc
        self.demo.vigilar(proc, trabajo)
        self.assertEqual(trabajo["estado"], "terminado")
        self.assertIsNone(self.demo.proceso)
        for n in range(510):
            self.demo.log(str(n))
        self.assertEqual(len(self.demo.logs), 500)

    def test_dos_acciones_no_corren_a_la_vez(self):
        self.demo.accion_lock.acquire()
        try:
            with self.assertRaises(ErrorDemo):
                self.demo.actuar("/demo/limpiar", {})
        finally:
            self.demo.accion_lock.release()

    def test_lanzamiento_usa_grupo_y_argumentos(self):
        self.demo.api_activa = lambda: True
        proc = Mock()
        self.demo.lanzar.return_value = proc
        with patch("demo.orquestador.threading.Thread"):
            self.demo.actuar("/demo/escenario", self.datos)
        self.assertTrue(self.demo.lanzar.call_args.kwargs["start_new_session"])
        self.assertNotIn("shell", self.demo.lanzar.call_args.kwargs)
        self.assertEqual(self.demo.trabajo["estado"], "corriendo")

    def test_cancelacion_limpia_y_deja_estado_reutilizable(self):
        self.demo.proceso = Mock()
        self.demo.trabajo = {"tipo": "red", "estado": "corriendo"}
        with patch.object(self.demo, "terminar_proceso") as terminar, patch.object(self.demo, "limpiar") as limpiar:
            self.demo.cancelar()
        terminar.assert_called_once()
        limpiar.assert_called_once_with(propia=True)
        self.assertFalse(self.demo.activo())
        self.assertEqual(self.demo.trabajo["estado"], "cancelado")
        self.assertIsNone(self.demo.proceso)

    def test_cancelacion_fuerza_grupo_si_no_responde(self):
        proc = Mock(pid=1234)
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired("prueba", 20), 0]
        with patch("demo.orquestador.os.killpg") as matar:
            self.demo.terminar_proceso(proc)
        import signal
        self.assertEqual([c.args for c in matar.call_args_list],
                         [(1234, signal.SIGTERM), (1234, signal.SIGKILL)])

    def test_sin_red_no_hay_evidencias(self):
        with self.assertRaises(ErrorDemo) as e:
            self.demo.evidencia("reglas", 1)
        self.assertEqual(e.exception.codigo, 409)
        self.run.assert_not_called()

    def test_limpiar_reinicia_ryu_venv_si_mn_lo_apaga(self):
        self.demo.cfg["controlador"] = "venv"
        self.demo.api_activa = Mock(side_effect=[True, False])
        self.run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(self.demo, "controlador") as controlador:
            self.demo.limpiar(propia=True)
        controlador.assert_called_once_with(True)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class RyuFalso(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ruta": self.path}).encode())

            do_PUT = do_GET
        cls.ryu = ThreadingHTTPServer(("127.0.0.1", 0), RyuFalso)
        cls.demo = Demo(vista_previa=True, api_url="http://127.0.0.1:%d" % cls.ryu.server_port)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), crear_handler(cls.demo))
        cls.url = "http://127.0.0.1:%d" % cls.server.server_port
        for server in (cls.ryu, cls.server):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server, cls.ryu):
            server.shutdown()
            server.server_close()

    def pedir(self, ruta, cuerpo=None, headers=None, metodo=None):
        r = urllib.request.Request(self.url + ruta, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                   headers={"Content-Type": "application/json", **(headers or {})}, method=metodo)
        return urllib.request.urlopen(r, timeout=3)

    def test_api_y_html_disponibles(self):
        with self.pedir("/demo/estado") as r:
            self.assertTrue(json.load(r)["vista_previa"])
        with self.pedir("/") as r:
            self.assertIn(b"Consola de QoS", r.read())
        with self.pedir("/panel?demo=1") as r:
            self.assertEqual(r.headers["X-Frame-Options"], "SAMEORIGIN")
            self.assertIn(b"Panel QoS", r.read())

    def test_proxy_preserva_query(self):
        with self.pedir("/qos/serie?minutos=2") as r:
            self.assertEqual(json.load(r)["ruta"], "/qos/serie?minutos=2")

    def test_rechaza_origen_host_y_rutas_ajenas(self):
        for ruta, headers, codigo in (("/demo/estado", {"Origin": "https://otro.test"}, 403),
                                      ("/demo/estado", {"Host": "otro.test"}, 403),
                                      ("/qos/administrar", {}, 404)):
            with self.subTest(ruta=ruta, headers=headers), self.assertRaises(urllib.error.HTTPError) as e:
                self.pedir(ruta, headers=headers)
            self.assertEqual(e.exception.code, codigo)

    def test_put_bloqueado_durante_escenario(self):
        self.demo.vista_previa = False
        self.demo.trabajo = {"tipo": "escenario", "estado": "corriendo"}
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.pedir("/qos/clasificador", {"nombre": "destino"}, metodo="PUT")
            self.assertEqual(e.exception.code, 409)
        finally:
            self.demo.vista_previa = True
            self.demo.trabajo = {"tipo": None, "estado": "inactivo"}

    def test_proxy_put_y_servidor_apagado(self):
        self.demo.vista_previa = False
        original = self.demo.api_url
        try:
            with self.pedir("/qos/clasificador", {"nombre": "destino"}, metodo="PUT") as r:
                self.assertEqual(json.load(r)["ruta"], "/qos/clasificador")
            self.demo.api_url = "http://127.0.0.1:1"
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.pedir("/qos/estado")
            self.assertEqual(e.exception.code, 503)
        finally:
            self.demo.api_url = original
            self.demo.vista_previa = True
