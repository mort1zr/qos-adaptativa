#!/usr/bin/env python3
"""
Aplicaciones simuladas para los perfiles de tráfico (historia PCIII-17).

Se ejecuta dentro de los equipos de Mininet (lo lanza trafico/generador.py).
Imita el COMPORTAMIENTO de cada aplicación (tamaños, ritmo, ráfagas), no su
contenido, y casi todo va por TCP 443 como el HTTPS real: el número de puerto no
revela qué aplicación es (así el clasificador del Sprint 4 tiene que aprender
del comportamiento, no del puerto).

Modos:
  servidor  --puerto 443
      Servidor TCP de muchas conexiones a la vez. Protocolo mínimo: el cliente
      manda una cabecera (operación, n, m) y luego:
        D  el servidor envía n bytes                       (descarga)
        U  el cliente envía n bytes, el servidor responde 1 (subida)
        T  el cliente envía n bytes, el servidor responde m (transacción)
  cliente   --destino IP --puerto 443 --patron P [opciones]
        descarga        pide bloques de 1 MB sin parar (TCP elástico)
        subida          envía bloques de 1 MB sin parar (respaldo)
        transacciones   peticiones de --peticion bytes y respuestas de
                        --respuesta bytes, con llegadas al azar (--tasa por s)
                        o fijas (--periodo s); --nueva-conexion para abrir y
                        cerrar en cada una (como un POS); --salida guarda en
                        JSON cuánto tardó cada una (p50, p95, máximo)
  udp       --destino IP --puerto P --mbps X --largo B [--variacion 0.2]
        flujo UDP de tasa casi constante (voz, video, cámaras)
  sumidero  --puerto P
        recibe y descarta UDP (evita mensajes ICMP "puerto inalcanzable")

Todos aceptan --duracion y --semilla (mismo azar en cada corrida).
Compatible con Python 3.9.
"""
import argparse
import json
import random
import signal
import socket
import socketserver
import struct
import sys
import threading
import time

CABECERA = struct.Struct("!cII")         # operación, n, m
CABECERA_UDP = struct.Struct("!IId")     # la misma que usan las sondas (experimentos/trafico.py)
BLOQUE = 65536
MB = 1024 * 1024


def _recibir_exacto(s, n):
    datos = bytearray()
    while len(datos) < n:
        parte = s.recv(min(BLOQUE * 4, n - len(datos)))
        if not parte:
            raise ConnectionError("conexión cerrada")
        datos += parte
    return bytes(datos)


def _descartar(s, n):
    """Lee y descarta n bytes."""
    falta = n
    while falta > 0:
        parte = s.recv(min(BLOQUE * 4, falta))
        if not parte:
            raise ConnectionError("conexión cerrada")
        falta -= len(parte)


def _enviar(s, n, relleno=b"\x00" * BLOQUE):
    falta = n
    while falta > 0:
        trozo = relleno[:min(BLOQUE, falta)]
        s.sendall(trozo)
        falta -= len(trozo)


# ---------------- servidor TCP ----------------
class _Manejador(socketserver.BaseRequestHandler):
    def handle(self):
        s = self.request
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            while True:
                op, n, m = CABECERA.unpack(_recibir_exacto(s, CABECERA.size))
                if op == b"D":
                    _enviar(s, n)
                elif op == b"U":
                    _descartar(s, n)
                    s.sendall(b"K")
                elif op == b"T":
                    _descartar(s, n)
                    _enviar(s, m)
                else:
                    return
        except (ConnectionError, OSError, struct.error):
            return


class _Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128


def servidor(puerto, duracion=None):
    srv = _Servidor(("0.0.0.0", puerto), _Manejador)
    if duracion:
        threading.Timer(duracion, srv.shutdown).start()
    srv.serve_forever()


# ---------------- cliente TCP ----------------
def conectar(destino, puerto, intentos=20):
    for _ in range(intentos):
        try:
            s = socket.create_connection((destino, puerto), timeout=5)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.settimeout(30)
            return s
        except OSError:
            time.sleep(0.5)
    raise ConnectionError(f"no se pudo conectar a {destino}:{puerto}")


def variar(rng, valor, variacion):
    """valor con una variación aleatoria de ±variacion (proporción), al menos 1."""
    if not variacion:
        return max(1, int(valor))
    return max(1, int(valor * rng.uniform(1 - variacion, 1 + variacion)))


def resumen_tiempos(tiempos_ms, errores=0):
    """p50, p95 y máximo de los tiempos de respuesta (ms)."""
    if not tiempos_ms:
        return {"transacciones": 0, "errores": errores}
    orden = sorted(tiempos_ms)
    pct = lambda q: orden[min(len(orden) - 1, int(q * len(orden)))]  # noqa: E731
    return {"transacciones": len(orden), "errores": errores, "p50_ms": round(pct(0.5), 1),
            "p95_ms": round(pct(0.95), 1), "max_ms": round(orden[-1], 1)}


def cliente(destino, puerto, patron, duracion, peticion=1000, respuesta=10000, tasa=None,
            periodo=None, nueva_conexion=False, variacion=0.3, semilla=1, salida=None):
    rng = random.Random(semilla)
    fin = time.time() + duracion
    tiempos, errores = [], 0
    try:
        s = None if nueva_conexion else conectar(destino, puerto)
    except ConnectionError:
        s, errores = None, 1
        if not nueva_conexion:
            _guardar(salida, resumen_tiempos(tiempos, errores))
            return 0
    hechas = 0
    masivo = patron in ("descarga", "subida")
    inicio = ultimo = time.time()
    try:
        if masivo:
            # Goodput: lo que llegó de verdad a la aplicación. Se cuentan bloques de 1 MB
            # completos (en la subida, confirmados por el servidor) y el tiempo hasta el último.
            while time.time() < fin:
                if patron == "descarga":
                    s.sendall(CABECERA.pack(b"D", MB, 0))
                    _descartar(s, MB)
                else:
                    s.sendall(CABECERA.pack(b"U", MB, 0))
                    _enviar(s, MB)
                    _recibir_exacto(s, 1)
                hechas += 1
                ultimo = time.time()
            return hechas
        # transacciones: llegadas al azar (Poisson) o periódicas
        proxima = time.time() + (rng.expovariate(tasa) if tasa else rng.uniform(0, periodo))
        while True:
            espera = proxima - time.time()
            if proxima >= fin:
                break
            if espera > 0:
                time.sleep(espera)
            n, m = variar(rng, peticion, variacion), variar(rng, respuesta, variacion)
            t0 = time.time()
            try:
                con = conectar(destino, puerto, intentos=3) if nueva_conexion else s
                con.sendall(CABECERA.pack(b"T", n, m))
                _enviar(con, n)
                _descartar(con, m)
                if nueva_conexion:
                    con.close()
                tiempos.append((time.time() - t0) * 1000)
                hechas += 1
            except (ConnectionError, OSError):
                errores += 1
                if not nueva_conexion:
                    raise
            proxima += rng.expovariate(tasa) if tasa else periodo
        return hechas
    except (ConnectionError, OSError):
        return hechas
    finally:
        if s:
            s.close()
        if masivo:
            segundos = max(ultimo - inicio, 1e-3)
            _guardar(salida, {"bytes": hechas * MB, "segundos": round(segundos, 2),
                              "mbps": round(hechas * MB * 8 / segundos / 1e6, 3), "errores": errores})
        else:
            _guardar(salida, resumen_tiempos(tiempos, errores))


def _guardar(salida, datos):
    if salida:
        with open(salida, "w") as f:
            json.dump(datos, f)


# ---------------- UDP ----------------
def udp(destino, puerto, mbps, largo, duracion, variacion=0.0, semilla=1):
    """Flujo UDP de ~mbps (contando 42 B de cabeceras por paquete). Devuelve paquetes enviados."""
    rng = random.Random(semilla)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pps = mbps * 1e6 / ((largo + 42) * 8)
    total = int(pps * duracion)
    inicio, t = time.time(), 0.0
    for seq in range(total):
        objetivo = inicio + t
        espera = objetivo - time.time()
        if espera > 0:
            time.sleep(espera)
        tam = variar(rng, largo, variacion) if variacion else largo
        relleno = b"\x00" * max(0, tam - CABECERA_UDP.size)
        try:
            s.sendto(CABECERA_UDP.pack(seq, total, time.time()) + relleno, (destino, puerto))
        except OSError:
            pass
        t += (1.0 / pps) * (rng.uniform(1 - variacion, 1 + variacion) if variacion else 1.0)
    s.close()
    return total


def sumidero(puerto, duracion):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * MB)
    s.bind(("0.0.0.0", puerto))
    s.settimeout(1.0)
    fin, recibidos = time.time() + duracion, 0
    while time.time() < fin:
        try:
            s.recvfrom(65535)
            recibidos += 1
        except socket.timeout:
            continue
    s.close()
    return recibidos


def main():
    p = argparse.ArgumentParser(description="Aplicaciones simuladas para los perfiles de tráfico")
    p.add_argument("modo", choices=["servidor", "cliente", "udp", "sumidero"])
    p.add_argument("--destino")
    p.add_argument("--puerto", type=int, default=443)
    p.add_argument("--duracion", type=float, default=60)
    p.add_argument("--semilla", type=int, default=1)
    p.add_argument("--patron", choices=["descarga", "subida", "transacciones"])
    p.add_argument("--peticion", type=int, default=1000)
    p.add_argument("--respuesta", type=int, default=10000)
    p.add_argument("--tasa", type=float, help="transacciones por segundo (llegadas al azar)")
    p.add_argument("--periodo", type=float, help="segundos entre transacciones (fijo)")
    p.add_argument("--nueva-conexion", action="store_true")
    p.add_argument("--variacion", type=float, default=0.3)
    p.add_argument("--mbps", type=float, default=1.0)
    p.add_argument("--largo", type=int, default=1200)
    p.add_argument("--salida", help="cliente: JSON con los tiempos de respuesta (transacciones) "
                                    "o con el goodput (descarga, subida)")
    a = p.parse_args()
    # Si el escenario la detiene (terminate), igual guarda su resultado.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if a.modo == "servidor":
        servidor(a.puerto, a.duracion)
    elif a.modo == "cliente":
        if a.patron == "transacciones" and not (a.tasa or a.periodo):
            sys.exit("transacciones necesita --tasa o --periodo")
        cliente(a.destino, a.puerto, a.patron, a.duracion, a.peticion, a.respuesta, a.tasa,
                a.periodo, a.nueva_conexion, a.variacion, a.semilla, a.salida)
    elif a.modo == "udp":
        udp(a.destino, a.puerto, a.mbps, a.largo, a.duracion, a.variacion, a.semilla)
    else:
        sumidero(a.puerto, a.duracion)


if __name__ == "__main__":
    main()
