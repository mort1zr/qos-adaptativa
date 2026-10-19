"""
Herramientas de medición de calidad (historia PCIII-13).

OpenFlow solo entrega contadores de bytes y paquetes; jitter, latencia y
pérdida se miden con sondas activas:
  - trafico.py imita una llamada (VoIP) o una videollamada en UDP. El receptor
    mide latencia de un sentido, jitter (RFC 3550) y pérdida, y guarda su
    resultado en un archivo local: nada viaja de vuelta por el enlace saturado.
  - trafico.py también genera las descargas TCP que saturan el enlace.
  - ping a intervalos cortos mide el tiempo de ida y vuelta (RTT).
  - El MOS de voz se estima con una aproximación del E-model (ITU-T G.107).
"""
import csv
import datetime
import json
import os
import re
import subprocess

# Objetivos de calidad. Pasarán a politicas.yaml en la historia PCIII-10.
OBJETIVOS = {"jitter_ms": 30.0, "perdida_pct": 1.0, "latencia_ms": 150.0, "mos": 4.0}

# Perfiles de las sondas
VOIP = {"pps": 50, "largo": 160}        # G.711: 50 paquetes/s de 160 bytes (64 kbps)
VIDEO = {"pps": 260, "largo": 1200}     # videollamada HD típica (~2.5 Mbps)

AQUI = os.path.dirname(os.path.abspath(__file__))
TRAFICO = os.path.join(AQUI, "trafico.py")
CSV_RESULTADOS = os.path.join(AQUI, "resultados", "mediciones.csv")
DIR_TMP = "/tmp/qos_mediciones"
CAMPOS = ["fecha", "escenario", "estrategia", "fase", "sede", "clase", "origen",
          "destino", "rtt_ms", "latencia_ms", "latencia_p95_ms", "jitter_ms",
          "jitter_max_ms", "perdida_pct", "mos", "mbps", "cumple"]

SILENCIO = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def mos(latencia_ms, jitter_ms, perdida_pct):
    """MOS estimado de voz (1 a 4.5) con una aproximación conocida del E-model."""
    efectiva = latencia_ms + 2 * jitter_ms + 10
    if efectiva < 160:
        r = 93.2 - efectiva / 40
    else:
        r = 93.2 - (efectiva - 120) / 10
    r = max(0.0, min(100.0, r - 2.5 * perdida_pct))
    return round(1 + 0.035 * r + 7e-6 * r * (r - 60) * (100 - r), 2)


# ---------------- procesos en los hosts de Mininet ----------------
def _ruta(host, puerto):
    os.makedirs(DIR_TMP, exist_ok=True)
    ruta = os.path.join(DIR_TMP, f"{host.name}_{puerto}.json")
    if os.path.exists(ruta):
        os.remove(ruta)
    return ruta


def receptor_udp(host, puerto, limite):
    """Receptor de una sonda UDP. Devuelve (proceso, archivo de resultado)."""
    ruta = _ruta(host, puerto)
    p = host.popen(["python3", TRAFICO, "udp-rx", "--puerto", str(puerto),
                    "--salida", ruta, "--limite", str(limite)], **SILENCIO)
    return p, ruta


def emisor_udp(origen, ip_destino, puerto, perfil, duracion):
    return origen.popen(["python3", TRAFICO, "udp-tx", "--destino", ip_destino,
                         "--puerto", str(puerto), "--pps", str(perfil["pps"]),
                         "--largo", str(perfil["largo"]), "--duracion", str(duracion)],
                        **SILENCIO)


def receptor_tcp(host, puerto, limite):
    ruta = _ruta(host, puerto)
    p = host.popen(["python3", TRAFICO, "tcp-rx", "--puerto", str(puerto),
                    "--salida", ruta, "--limite", str(limite)], **SILENCIO)
    return p, ruta


def emisor_tcp(origen, ip_destino, puerto, duracion):
    return origen.popen(["python3", TRAFICO, "tcp-tx", "--destino", ip_destino,
                         "--puerto", str(puerto), "--duracion", str(duracion)], **SILENCIO)


def sonda_ping(origen, ip_destino, duracion, intervalo=0.1):
    n = max(1, int(duracion / intervalo))
    return origen.popen(["ping", "-i", str(intervalo), "-c", str(n), ip_destino])


def esperar(proceso, limite=15):
    """Espera a que termine un proceso; si se pasa del límite, lo detiene."""
    try:
        proceso.wait(timeout=limite)
    except subprocess.TimeoutExpired:
        proceso.terminate()
        proceso.wait(timeout=5)


# ---------------- lectura de resultados ----------------
def leer(proceso):
    salida, _ = proceso.communicate()
    return salida.decode(errors="replace") if isinstance(salida, bytes) else (salida or "")


def leer_json(ruta):
    try:
        with open(ruta) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def resultado_udp(ruta):
    """Latencia de un sentido, jitter promedio/máximo, pérdida y Mbps del receptor."""
    d = leer_json(ruta)
    if not d:
        return {"error": f"el receptor no dejó resultado en {ruta}"}
    return d


def resultado_tcp(ruta):
    d = leer_json(ruta)
    if not d:
        return {"error": f"el receptor no dejó resultado en {ruta}", "mbps": 0.0}
    return d


def resultado_ping(texto):
    tiempos = [float(t) for t in re.findall(r"time=([\d.]+)", texto)]
    m = re.search(r"([\d.]+)% packet loss", texto)
    perdida = float(m.group(1)) if m else 100.0
    if not tiempos:
        return {"rtt_ms": None, "rtt_p95_ms": None, "perdida_pct": perdida}
    tiempos.sort()
    p95 = tiempos[min(len(tiempos) - 1, int(0.95 * len(tiempos)))]
    return {"rtt_ms": round(sum(tiempos) / len(tiempos), 1),
            "rtt_p95_ms": round(p95, 1), "perdida_pct": perdida}


def evaluar(fila):
    """Compara una fila de tráfico sensible contra los objetivos.
    La latencia se evalúa con el percentil 95 (como en los SLA): el promedio
    esconde los paquetes que llegan tarde y que un teléfono descartaría."""
    fallas = []
    latencia = fila.get("latencia_p95_ms", fila.get("latencia_ms"))
    if fila.get("jitter_ms") is not None and fila["jitter_ms"] > OBJETIVOS["jitter_ms"]:
        fallas.append("jitter")
    if fila.get("perdida_pct") is not None and fila["perdida_pct"] > OBJETIVOS["perdida_pct"]:
        fallas.append("pérdida")
    if latencia is not None and latencia > OBJETIVOS["latencia_ms"]:
        fallas.append("latencia p95")
    if fila.get("mos") is not None and fila["mos"] < OBJETIVOS["mos"]:
        fallas.append("MOS")
    return "sí" if not fallas else "no (" + ", ".join(fallas) + ")"


def guardar(filas, ruta=CSV_RESULTADOS):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    nuevo = not os.path.exists(ruta)
    fecha = datetime.datetime.now().isoformat(timespec="seconds")
    with open(ruta, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction="ignore")
        if nuevo:
            w.writeheader()
        for fila in filas:
            w.writerow({"fecha": fecha, **fila})
    return ruta
