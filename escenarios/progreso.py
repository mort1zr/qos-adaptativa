"""Publica las fases de una demo sin cambiar sus mediciones."""
import json
import os
import time
from pathlib import Path


class Progreso:
    def __init__(self, ruta):
        self.ruta = Path(ruta)
        self.datos = {}

    def guardar(self):
        self.datos["actualizado"] = time.time()
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = self.ruta.with_name(self.ruta.name + ".tmp")
        try:
            temporal.write_text(json.dumps(self.datos, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            os.replace(str(temporal), str(self.ruta))
            from escenarios.escenario import devolver_al_usuario
            devolver_al_usuario(str(self.ruta))
        finally:
            if temporal.exists():
                temporal.unlink()

    def iniciar(self, datos, planes, estrategias, parametros, objetivos):
        self.datos = {"version": 1, "estado": "corriendo", "parametros": parametros,
                      "objetivos": objetivos, "error": None, "corridas": []}
        for estrategia in estrategias:
            for nombre, fases in planes.items():
                self.datos["corridas"].append({
                    "escenario": nombre, "estrategia": estrategia,
                    "descripcion": datos["escenarios"][nombre]["descripcion"],
                    "fases": [{"nombre": f["nombre"], "duracion_s": f["duracion_s"],
                               "enlace": f.get("enlace"), "estado": "pendiente",
                               "metricas": None, "cumple": None} for f in fases]})
        self.guardar()

    def fase(self, escenario, estrategia, nombre):
        corrida = next(c for c in self.datos["corridas"]
                       if c["escenario"] == escenario and c["estrategia"] == estrategia)
        return next(f for f in corrida["fases"] if f["nombre"] == nombre)

    def empezar_fase(self, escenario, estrategia, nombre, hora):
        self.fase(escenario, estrategia, nombre).update(
            estado="corriendo", inicio_real=time.time(), fin_real=None, hora_simulada=hora)
        self.guardar()

    def terminar_fase(self, escenario, estrategia, nombre, fila):
        cumple = {k: None if fila.get("cumple_" + k) is None
                  else str(fila["cumple_" + k]).startswith("sí") for k in ("voz", "pagos", "web")}
        valida = fila.get("valida")
        if not isinstance(valida, bool):
            valida = str(valida).startswith("sí")
        self.fase(escenario, estrategia, nombre).update(
            estado="terminada", fin_real=time.time(), metricas=dict(fila), cumple=cumple, valida=valida)
        self.guardar()

    def finalizar(self, estado="terminado", error=None):
        self.datos.update(estado=estado, error=error)
        self.guardar()
