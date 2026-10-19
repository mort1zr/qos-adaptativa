#!/usr/bin/env python3
"""
Generador y receptor de tráfico de prueba (historia PCIII-13).

Reemplaza a iperf3 en las mediciones: el receptor calcula todo localmente y
escribe su resultado en un archivo, sin intercambiar nada por la red (con el
enlace saturado, ese intercambio de iperf3 fallaba).

En Mininet todos los hosts comparten el reloj del sistema, así que cada paquete
UDP lleva la hora de envío y el receptor mide la latencia de UN SOLO SENTIDO
real. (En una red física esto exigiría relojes sincronizados con NTP/PTP.)

Modos:
  udp-tx  --destino IP --puerto P --pps N --largo BYTES --duracion S
  udp-rx  --puerto P --salida archivo.json --limite S
  tcp-tx  --destino IP --puerto P --duracion S
  tcp-rx  --puerto P --salida archivo.json --limite S
"""
import argparse
import json
import socket
import struct
import sys
import time

CABECERA = struct.Struct("!IId")   # número de secuencia, total previsto, hora de envío


# ---------------- UDP: sondas de voz y video ----------------
def udp_tx(destino, puerto, pps, largo, duracion):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    total = int(pps * duracion)
    relleno = b"\x00" * max(0, largo - CABECERA.size)
    intervalo = 1.0 / pps
    inicio = time.time()
    for seq in range(total):
        objetivo = inicio + seq * intervalo
        espera = objetivo - time.time()
        if espera > 0:
            time.sleep(espera)
        try:
            s.sendto(CABECERA.pack(seq, total, time.time()) + relleno, (destino, puerto))
        except OSError:
            pass   # cola local llena: cuenta como pérdida


def udp_rx(puerto, salida, limite):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    s.bind(("0.0.0.0", puerto))
    s.settimeout(0.5)
    fin_limite = time.time() + limite
    vistos, total, ultimo = set(), 0, None
    retardos = []                 # latencia de un sentido (ms) por paquete, en orden de llegada
    jitter, transito_prev = 0.0, None
    jitter_por_segundo = {}       # segundo -> [valores de jitter]
    t0, bytes_rx = None, 0
    while time.time() < fin_limite:
        try:
            datos, _ = s.recvfrom(65535)
        except socket.timeout:
            if ultimo is not None and time.time() - ultimo > 2.0:
                break             # 2 s sin paquetes tras empezar: terminó
            continue
        ahora = time.time()
        if len(datos) < CABECERA.size:
            continue
        seq, tot, enviado = CABECERA.unpack_from(datos)
        t0 = t0 or ahora
        ultimo, total = ahora, max(total, tot)
        bytes_rx += len(datos)
        if seq in vistos:
            continue
        vistos.add(seq)
        transito = (ahora - enviado) * 1000.0
        retardos.append(transito)
        if transito_prev is not None:   # jitter según RFC 3550
            jitter += (abs(transito - transito_prev) - jitter) / 16.0
        transito_prev = transito
        jitter_por_segundo.setdefault(int(ahora - t0), []).append(jitter)

    res = {"recibidos": len(vistos), "previstos": total}
    if retardos:
        orden = sorted(retardos)
        p95 = orden[min(len(orden) - 1, int(0.95 * len(orden)))]
        medias = [sum(v) / len(v) for v in jitter_por_segundo.values()]
        dur = max(1e-6, (ultimo - t0))
        res.update({
            "latencia_ms": round(sum(retardos) / len(retardos), 2),
            "latencia_p95_ms": round(p95, 2),
            "jitter_ms": round(sum(medias) / len(medias), 2),
            "jitter_max_ms": round(max(medias), 2),
            "perdida_pct": round(100.0 * (1 - len(vistos) / total), 2) if total else 100.0,
            "mbps": round(bytes_rx * 8 / dur / 1e6, 3),
        })
    else:
        res.update({"error": "no llegó ningún paquete", "perdida_pct": 100.0})
    with open(salida, "w") as f:
        json.dump(res, f)


# ---------------- TCP: descargas y respaldos ----------------
def tcp_tx(destino, puerto, duracion):
    bloque = b"\x00" * 65536
    for _ in range(20):           # reintenta si el receptor aún no está listo
        try:
            s = socket.create_connection((destino, puerto), timeout=5)
            break
        except OSError:
            time.sleep(0.5)
    else:
        sys.exit(f"no se pudo conectar a {destino}:{puerto}")
    s.settimeout(None)
    fin = time.time() + duracion
    try:
        while time.time() < fin:
            s.sendall(bloque)
    except OSError:
        pass
    s.close()


def tcp_rx(puerto, salida, limite):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", puerto))
    srv.listen(1)
    srv.settimeout(limite)
    res = {}
    try:
        con, _ = srv.accept()
        con.settimeout(5)
        total, t0, t1 = 0, None, None
        while True:
            try:
                datos = con.recv(262144)
            except socket.timeout:
                break
            if not datos:
                break
            t0 = t0 or time.time()
            t1 = time.time()
            total += len(datos)
        dur = max(1e-6, (t1 - t0)) if t0 else 0
        res = {"bytes": total, "segundos": round(dur, 2),
               "mbps": round(total * 8 / dur / 1e6, 2) if dur else 0.0}
    except socket.timeout:
        res = {"error": "nadie se conectó", "mbps": 0.0}
    with open(salida, "w") as f:
        json.dump(res, f)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("modo", choices=["udp-tx", "udp-rx", "tcp-tx", "tcp-rx"])
    p.add_argument("--destino")
    p.add_argument("--puerto", type=int, required=True)
    p.add_argument("--pps", type=float, default=50)
    p.add_argument("--largo", type=int, default=160)
    p.add_argument("--duracion", type=float, default=20)
    p.add_argument("--salida")
    p.add_argument("--limite", type=float, default=60)
    a = p.parse_args()
    if a.modo == "udp-tx":
        udp_tx(a.destino, a.puerto, a.pps, a.largo, a.duracion)
    elif a.modo == "udp-rx":
        udp_rx(a.puerto, a.salida, a.limite)
    elif a.modo == "tcp-tx":
        tcp_tx(a.destino, a.puerto, a.duracion)
    else:
        tcp_rx(a.puerto, a.salida, a.limite)


if __name__ == "__main__":
    main()
