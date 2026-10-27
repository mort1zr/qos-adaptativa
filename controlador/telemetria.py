"""
Telemetría por flujo, área y clase con histórico en SQLite (historia PCIII-16).

La aplicación de Ryu (qos_app.py) le pasa, cada pocos segundos, los contadores
de los flujos y de los puertos de los switches de acceso. Este módulo:
  - calcula la tasa (Mbps) de cada flujo con la diferencia entre dos lecturas;
  - atribuye cada flujo al equipo de la sede (área, segmento, tipo) y lo
    clasifica con las políticas según el servicio del otro extremo;
  - guarda el detalle por flujo, el agregado por área y clase, y el uso de cada
    enlace, con marca de tiempo.

Privacidad (Ley 29733): nunca se ve el contenido de los paquetes, solo
contadores. El detalle por flujo identifica equipos y se borra pasadas
'retencion_h' horas; el agregado por área y clase se conserva.

No depende de Ryu: se prueba con controlador/test_telemetria.py.
Compatible con Python 3.9.
"""
import math
import os
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

from controlador.clasificadores import PorPolitica, armar_flujo

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DEFECTO = os.path.join(RAIZ, "datos", "telemetria.db")
CONFIG = os.path.join(RAIZ, "controlador", "telemetria.yaml")


def leer_config(ruta: str = CONFIG) -> dict:
    """Configuración de la telemetría (controlador/telemetria.yaml) con valores por defecto."""
    cfg = {"intervalo_s": 5, "idle_timeout_s": 30, "retencion_flujos_h": 24,
           "base_datos": "datos/telemetria.db", "clasificador": "ninguno"}
    if os.path.exists(ruta):
        import yaml
        with open(ruta) as f:
            cfg.update(yaml.safe_load(f) or {})
    if not os.path.isabs(cfg["base_datos"]):
        cfg["base_datos"] = os.path.join(RAIZ, cfg["base_datos"])
    return cfg

ESQUEMA = """
CREATE TABLE IF NOT EXISTS flujos (
    ts REAL, sede_id INTEGER, sentido TEXT, origen_ip TEXT, destino_ip TEXT, proto INTEGER,
    origen TEXT, destino TEXT, local TEXT, area TEXT, segmento TEXT, tipo TEXT,
    servicio TEXT, clase TEXT, bytes INTEGER, paquetes INTEGER, segundos REAL,
    mbps REAL, pps REAL);
CREATE INDEX IF NOT EXISTS flujos_ts ON flujos(ts);
CREATE TABLE IF NOT EXISTS areas (
    ts REAL, sede_id INTEGER, sede TEXT, area TEXT, clase TEXT, sentido TEXT,
    mbps REAL, segundos REAL, flujos INTEGER);
CREATE INDEX IF NOT EXISTS areas_ts ON areas(ts, area);
CREATE TABLE IF NOT EXISTS enlaces (
    ts REAL, sede_id INTEGER, sentido TEXT, mbps REAL, pps REAL, descartes INTEGER,
    capacidad_mbps REAL, segundos REAL);
CREATE INDEX IF NOT EXISTS enlaces_ts ON enlaces(ts);
CREATE TABLE IF NOT EXISTS sondeos (ts REAL, sede_id INTEGER, segundos REAL);
CREATE INDEX IF NOT EXISTS sondeos_ts ON sondeos(ts);
CREATE TABLE IF NOT EXISTS decisiones (
    ts REAL, dpid INTEGER, sede_id INTEGER, sentido TEXT, origen_ip TEXT, destino_ip TEXT,
    proto INTEGER, origen TEXT, destino TEXT, area TEXT, clasificador TEXT, clase TEXT,
    cola INTEGER, motivo TEXT, ms REAL, servicio TEXT, via TEXT);
CREATE INDEX IF NOT EXISTS decisiones_ts ON decisiones(ts);
"""
CAMPOS_DECISION = ("ts", "dpid", "sede_id", "sentido", "origen_ip", "destino_ip", "proto", "origen",
                   "destino", "area", "clasificador", "clase", "cola", "motivo", "ms", "servicio", "via")
# Columnas agregadas después de crear la tabla (PCIII-20): se suman a las bases existentes.
COLUMNAS_NUEVAS = {"decisiones": ("servicio", "via")}

PROTOCOLOS = {1: "icmp", 6: "tcp", 17: "udp"}
NO_DISPONIBLE = 2 ** 64 - 1     # OpenFlow informa así un contador que el switch no tiene


def _contador(valor):
    """None si el switch no tiene ese contador; si no, el valor."""
    return None if valor is None or valor >= NO_DISPONIBLE else valor


class Telemetria:
    def __init__(self, inventario, politicas, ruta_db: str = DB_DEFECTO,
                 intervalo_s: float = 5.0, retencion_h: float = 24.0):
        self.inv = inventario
        self.pol = politicas
        self.intervalo_s = intervalo_s
        self.retencion_s = retencion_h * 3600
        os.makedirs(os.path.dirname(ruta_db) or ".", exist_ok=True)
        self.db = sqlite3.connect(ruta_db, check_same_thread=False)
        self.db.executescript(ESQUEMA)
        self._migrar()
        self._flujos: Dict[tuple, Tuple[int, int, float]] = {}   # clave -> (bytes, paquetes, ts)
        self._puertos: Dict[tuple, Tuple[int, int, float]] = {}
        self._descartes: Dict[tuple, int] = {}                     # puerto -> tx_dropped anterior
        self._sondeos: Dict[int, float] = {}                       # sede -> ts del sondeo anterior
        self._politica = PorPolitica(politicas)

    def _migrar(self):
        for tabla, columnas in COLUMNAS_NUEVAS.items():
            existentes = {fila[1] for fila in self.db.execute(f"PRAGMA table_info({tabla})")}
            for c in columnas:
                if c not in existentes:
                    self.db.execute(f"ALTER TABLE {tabla} ADD COLUMN {c} TEXT")
        self.db.commit()

    # ---------------- quién es quién ----------------
    def describir(self, sw: dict, origen_ip: str, destino_ip: str, in_port: int) -> dict:
        """Sentido, equipo local (de la sede del switch), área, servicio y clase de un flujo.

        La clase es la que dice la política (la "etiqueta verdadera" del flujo),
        aunque el controlador esté usando otro clasificador: así la telemetría
        sirve de referencia para comparar estrategias y para entrenar a la IA.
        """
        flujo = armar_flujo(self.inv, sw, origen_ip, destino_ip, 0, in_port, ts=0)
        local, o, d = flujo.local, self.inv.equipo(origen_ip), self.inv.equipo(destino_ip)
        servicio = self._politica.servicio(flujo)
        clase = self._politica.clasificar(flujo).clase
        return {
            "sentido": flujo.sentido, "servicio": servicio, "clase": clase,
            "local": local["nombre"] if local else "", "area": local["area"] if local else "Desconocida",
            "segmento": local["segmento"] if local else "", "tipo": local["tipo"] if local else "",
            "sede": local["sede"] if local else "",
            "origen": o["nombre"] if o else origen_ip, "destino": d["nombre"] if d else destino_ip,
        }

    # ---------------- contadores de flujos ----------------
    def _tasa(self, memoria, clave, bytes_, paquetes, ts, duracion_s):
        """Bytes, paquetes y segundos desde la lectura anterior de este contador."""
        previo = memoria.get(clave)
        memoria[clave] = (bytes_, paquetes, ts)
        if previo and bytes_ >= previo[0]:
            return bytes_ - previo[0], paquetes - previo[1], max(ts - previo[2], 1e-3)
        # Contador nuevo (o reiniciado): su tasa desde que existe.
        segundos = duracion_s if duracion_s else self.intervalo_s
        return bytes_, paquetes, max(min(segundos, self.intervalo_s * 3), 1e-3)

    def registrar_flujos(self, dpid: int, muestras: List[dict], ts: Optional[float] = None,
                         eliminados: bool = False) -> List[dict]:
        """Registra la lectura de los flujos de un switch de acceso.

        muestras: [{origen_ip, destino_ip, proto, in_port, bytes, paquetes, duracion_s}]
        eliminados=True para flujos que el switch acaba de borrar (sus últimos bytes).
        Devuelve las filas por flujo guardadas.
        """
        ts = time.time() if ts is None else ts
        sw = self.inv.switch(dpid)
        if not sw or sw["tipo"] != "acceso":
            return []
        filas, por_area = [], {}
        for mu in muestras:
            clave = (dpid, mu["origen_ip"], mu["destino_ip"], mu["proto"], mu["in_port"])
            db, dp, seg = self._tasa(self._flujos, clave, mu["bytes"], mu["paquetes"], ts,
                                     mu.get("duracion_s"))
            if eliminados:
                self._flujos.pop(clave, None)
            if db <= 0:
                continue
            info = self.describir(sw, mu["origen_ip"], mu["destino_ip"], mu["in_port"])
            fila = dict(info, ts=ts, sede_id=sw["sede_id"], origen_ip=mu["origen_ip"],
                        destino_ip=mu["destino_ip"], proto=mu["proto"], bytes=db, paquetes=dp,
                        segundos=round(seg, 3), mbps=db * 8 / seg / 1e6, pps=dp / seg)
            filas.append(fila)
            k = (fila["area"], fila["clase"], fila["sentido"], fila["sede"])
            a = por_area.setdefault(k, [0.0, 0.0, 0])
            a[0] += db * 8 / 1e6        # megabits
            a[1] = max(a[1], seg)
            a[2] += 1
        if not eliminados:
            self._purgar(dpid, ts)
        self.db.executemany(
            "INSERT INTO flujos VALUES (:ts,:sede_id,:sentido,:origen_ip,:destino_ip,:proto,:origen,"
            ":destino,:local,:area,:segmento,:tipo,:servicio,:clase,:bytes,:paquetes,:segundos,"
            ":mbps,:pps)", filas)
        # Agregado por área: los megabits del intervalo repartidos en el intervalo del sondeo.
        segundos_sondeo = self._intervalo_sondeo(sw["sede_id"], ts, eliminados)
        self.db.executemany(
            "INSERT INTO areas VALUES (?,?,?,?,?,?,?,?,?)",
            [(ts, sw["sede_id"], sede, area, clase, sentido,
              megabits / (seg_flujo if eliminados else segundos_sondeo),
              seg_flujo if eliminados else segundos_sondeo, n)
             for (area, clase, sentido, sede), (megabits, seg_flujo, n) in por_area.items()])
        self.db.commit()
        return filas

    def _intervalo_sondeo(self, sede_id, ts, eliminados):
        if eliminados:
            return self.intervalo_s
        anterior = self._sondeos.get(sede_id)
        segundos = ts - anterior if anterior else self.intervalo_s
        segundos = min(max(segundos, 1e-3), self.intervalo_s * 3)
        self._sondeos[sede_id] = ts
        self.db.execute("INSERT INTO sondeos VALUES (?,?,?)", (ts, sede_id, segundos))
        return segundos

    def _purgar(self, dpid, ts):
        """Olvida flujos que no aparecen hace rato (expiraron en el switch)."""
        limite = ts - self.intervalo_s * 4
        for clave in [k for k, v in self._flujos.items() if k[0] == dpid and v[2] < limite]:
            del self._flujos[clave]

    # ---------------- contadores de puertos (uso del enlace) ----------------
    def registrar_puertos(self, dpid: int, puertos: List[dict], ts: Optional[float] = None) -> List[dict]:
        """puertos: [{port_no, tx_bytes, tx_packets, tx_dropped}] de un switch de acceso.
        Lo que SALE hacia el operador es subida de la sede; hacia la sede, bajada."""
        ts = time.time() if ts is None else ts
        sw = self.inv.switch(dpid)
        if not sw or sw["tipo"] != "acceso":
            return []
        filas = []
        for p in puertos:
            if p["port_no"] == sw["puerto_operador"]:
                sentido = "subida"
            elif p["port_no"] == sw["puerto_sede"]:
                sentido = "bajada"
            else:
                continue
            clave = (dpid, p["port_no"])
            if _contador(p.get("tx_bytes")) is None or _contador(p.get("tx_packets")) is None:
                # El switch respondió "no disponible" (2^64 - 1): se ignora la lectura y se
                # conserva la anterior, para no confundirla con billones de Mbps.
                continue
            previo = self._puertos.get(clave)
            db, dp, seg = self._tasa(self._puertos, clave, p["tx_bytes"], p["tx_packets"], ts, None)
            actual = _contador(p.get("tx_dropped"))
            anterior = self._descartes.get(clave)
            descartes = actual - anterior if actual is not None and anterior is not None else None
            self._descartes[clave] = actual
            if not previo or p["tx_bytes"] < previo[0]:
                # La primera lectura (o la de un puerto recreado al rearmar la red) solo
                # sirve de referencia: no se sabe en cuánto tiempo se juntaron esos bytes.
                continue
            filas.append({"ts": ts, "sede_id": sw["sede_id"], "sentido": sentido,
                          "mbps": db * 8 / seg / 1e6, "pps": dp / seg,
                          "descartes": max(descartes, 0) if descartes is not None else None,
                          "capacidad_mbps": sw["mbps"], "segundos": seg})
        self.db.executemany("INSERT INTO enlaces VALUES (:ts,:sede_id,:sentido,:mbps,:pps,:descartes,"
                            ":capacidad_mbps,:segundos)", filas)
        self.db.commit()
        return filas

    # ---------------- decisiones del clasificador (PCIII-19) ----------------
    def registrar_decisiones(self, decisiones: List[dict]) -> int:
        """Guarda las decisiones del controlador (una por flujo nuevo): qué clase y cola
        eligió, con qué clasificador, por qué y cuánto tardó. La aplicación de Ryu las
        acumula y las guarda en el sondeo, para no escribir en disco con cada packet-in."""
        if not decisiones:
            return 0
        self.db.executemany(
            f"INSERT INTO decisiones VALUES ({','.join(':' + c for c in CAMPOS_DECISION)})",
            [{c: d.get(c) for c in CAMPOS_DECISION} for d in decisiones])
        self.db.commit()
        return len(decisiones)

    # ---------------- mantenimiento ----------------
    def limpiar(self, ts: Optional[float] = None) -> int:
        """Borra el detalle por flujo y las decisiones más antiguas que la retención
        (identifican equipos). Devuelve filas borradas."""
        ts = time.time() if ts is None else ts
        borradas = 0
        for tabla in ("flujos", "decisiones"):
            borradas += self.db.execute(f"DELETE FROM {tabla} WHERE ts < ?",
                                        (ts - self.retencion_s,)).rowcount
        self.db.commit()
        return borradas


# ---------------- consultas ----------------
def demanda(db_path: str = DB_DEFECTO, minutos: float = 10, area: Optional[str] = None,
            sede_id: Optional[int] = None, ahora: Optional[float] = None,
            por: str = "area") -> List[dict]:
    """Demanda en los últimos 'minutos', por área (o por clase), sentido y clase.

    Devuelve filas con: sede, area, clase, sentido, promedio_mbps (sobre todo el
    periodo con telemetría, contando los ratos sin tráfico como 0) y maximo_mbps
    (el mayor valor de un sondeo).
    """
    ahora = time.time() if ahora is None else ahora
    desde = ahora - minutos * 60
    con = sqlite3.connect(db_path)
    filtro, args = "ts >= ? AND ts <= ?", [desde, ahora]
    if area:
        filtro += " AND lower(area) = lower(?)"
        args.append(area)
    if sede_id is not None:
        filtro += " AND sede_id = ?"
        args.append(sede_id)
    filas = con.execute(f"SELECT ts, sede_id, sede, area, clase, sentido, mbps, segundos "
                        f"FROM areas WHERE {filtro}", args).fetchall()
    cubierto = dict(con.execute(
        "SELECT sede_id, SUM(segundos) FROM sondeos WHERE ts >= ? AND ts <= ? GROUP BY sede_id",
        (desde, ahora)).fetchall())
    con.close()
    grupos: Dict[tuple, dict] = {}
    for ts, sid, sede, ar, clase, sentido, mbps, seg in filas:
        clave = (sid, sede, ar if por == "area" else "(todas)", clase, sentido)
        g = grupos.setdefault(clave, {"megabits": 0.0, "por_ts": {}})
        g["megabits"] += mbps * seg
        g["por_ts"][ts] = g["por_ts"].get(ts, 0.0) + mbps
    salida = []
    for (sid, sede, ar, clase, sentido), g in sorted(grupos.items(), key=lambda x: (x[0][0], x[0][2], x[0][4], x[0][3])):
        segundos = cubierto.get(sid) or minutos * 60
        salida.append({"sede_id": sid, "sede": sede, "area": ar, "clase": clase, "sentido": sentido,
                       "promedio_mbps": round(g["megabits"] / segundos, 3),
                       "maximo_mbps": round(max(g["por_ts"].values()), 3),
                       "segundos_con_datos": round(segundos, 1)})
    return salida


def percentil(valores: List[float], p: float) -> Optional[float]:
    """Percentil p (0-100) por el método del rango más cercano."""
    if not valores:
        return None
    v = sorted(valores)
    k = max(0, min(len(v) - 1, math.ceil(p / 100 * len(v)) - 1))
    return v[k]


def resumen_decisiones(db_path: str = DB_DEFECTO, minutos: float = 10, ahora: Optional[float] = None,
                       sede_id: Optional[int] = None) -> List[dict]:
    """Decisiones del controlador en los últimos 'minutos': cuántas por clasificador y
    clase, y cuánto tardó cada una (p50, p95 y máximo, en ms)."""
    ahora = time.time() if ahora is None else ahora
    filtro, args = "ts >= ? AND ts <= ?", [ahora - minutos * 60, ahora]
    if sede_id is not None:
        filtro += " AND sede_id = ?"
        args.append(sede_id)
    con = sqlite3.connect(db_path)
    try:
        filas = con.execute(f"SELECT clasificador, clase, cola, ms, COALESCE(via, 'reactiva') "
                            f"FROM decisiones WHERE {filtro}", args).fetchall()
    except sqlite3.OperationalError:        # base del Sprint 2, sin la tabla todavía
        filas = []
    con.close()
    grupos: Dict[tuple, List[float]] = {}
    vias: Dict[tuple, Dict[str, int]] = {}
    for clasificador, clase, cola, ms, via in filas:
        grupos.setdefault((clasificador, clase, cola), []).append(ms)
        v = vias.setdefault((clasificador, clase, cola), {})
        v[via] = v.get(via, 0) + 1
    return [{"clasificador": c, "clase": k, "cola": q, "decisiones": len(ms),
             "p50_ms": round(percentil(ms, 50), 2), "p95_ms": round(percentil(ms, 95), 2),
             "max_ms": round(max(ms), 2), "proactivas": vias[(c, k, q)].get("proactiva", 0)}
            for (c, k, q), ms in sorted(grupos.items(), key=lambda x: (x[0][0], x[0][2]))]


def uso_enlaces(db_path: str = DB_DEFECTO, minutos: float = 10,
                ahora: Optional[float] = None) -> List[dict]:
    ahora = time.time() if ahora is None else ahora
    con = sqlite3.connect(db_path)
    filas = con.execute(
        "SELECT sede_id, sentido, SUM(mbps*segundos)/SUM(segundos), MAX(mbps), MAX(capacidad_mbps), "
        "SUM(descartes) FROM enlaces WHERE ts >= ? AND ts <= ? GROUP BY sede_id, sentido "
        "ORDER BY sede_id, sentido", (ahora - minutos * 60, ahora)).fetchall()
    con.close()
    return [{"sede_id": s, "sentido": se, "promedio_mbps": round(p or 0, 3), "maximo_mbps": round(mx or 0, 3),
             "capacidad_mbps": c, "uso_pct": round(100 * (p or 0) / c, 1) if c else None,
             "descartes": d} for s, se, p, mx, c, d in filas]


# ---------------- panel en vivo (Sprint 3: visualización) ----------------
def serie_enlaces(db_path: str = DB_DEFECTO, minutos: float = 10, ahora: Optional[float] = None) -> dict:
    """Uso de cada enlace de acceso en el tiempo: {sede: {sentido: [[ts, mbps], ...]}, ...}
    con la capacidad de cada sede en '_capacidad'."""
    ahora = time.time() if ahora is None else ahora
    con = sqlite3.connect(db_path)
    try:
        filas = con.execute("SELECT ts, sede_id, sentido, mbps, capacidad_mbps FROM enlaces "
                            "WHERE ts >= ? AND ts <= ? ORDER BY ts", (ahora - minutos * 60, ahora)).fetchall()
    except sqlite3.OperationalError:
        filas = []
    con.close()
    salida: Dict[str, dict] = {}
    for ts, sede, sentido, mbps, cap in filas:
        s = salida.setdefault(str(sede), {"subida": [], "bajada": [], "_capacidad": cap})
        s[sentido].append([round(ts, 1), round(mbps, 3)])
    return salida


def datos_panel(db_path: str = DB_DEFECTO, minutos: float = 5, ahora: Optional[float] = None) -> dict:
    """Todo lo que muestra el panel: uso de los enlaces, demanda por clase y por área
    (los dos sentidos sumados) y las decisiones del controlador, de los últimos minutos."""
    ahora = time.time() if ahora is None else ahora
    try:
        clases = demanda(db_path, minutos, ahora=ahora, por="clase")
        areas = demanda(db_path, minutos, ahora=ahora, por="area")
        enlaces = uso_enlaces(db_path, minutos, ahora=ahora)
    except sqlite3.OperationalError:          # base vacía: el controlador aún no guardó nada
        clases, areas, enlaces = [], [], []
    por_area: Dict[tuple, float] = {}
    for f in areas:
        k = (f["sede_id"], f["sede"], f["area"], f["clase"])
        por_area[k] = por_area.get(k, 0.0) + f["promedio_mbps"]
    top_areas = sorted(({"sede_id": k[0], "sede": k[1], "area": k[2], "clase": k[3], "mbps": round(v, 3)}
                        for k, v in por_area.items() if v >= 0.001), key=lambda x: -x["mbps"])[:12]
    return {"ahora": ahora, "minutos": minutos, "enlaces": enlaces,
            "clases": [f for f in clases if f["maximo_mbps"] >= 0.001],
            "areas": top_areas, "decisiones": resumen_decisiones(db_path, minutos, ahora=ahora)}
