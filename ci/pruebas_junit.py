#!/usr/bin/env python3
"""Corre las pruebas unitarias del proyecto y guarda el resultado en formato JUnit XML.

Es lo que usa el pipeline de Azure DevOps (azure-pipelines.yml): la tarea
PublishTestResults lee ese XML y muestra cada prueba en la pestaña "Tests" del
build. Solo usa la librería estándar, así que corre en cualquier agente.

    python3 ci/pruebas_junit.py                       # todas, informe en resultados-pruebas.xml
    python3 ci/pruebas_junit.py --salida informe.xml --nombre "Python 3.9"

Sale con código 1 si alguna prueba falla (el pipeline se marca en rojo).
"""
import argparse
import os
import platform
import sys
import time
import traceback
import unittest
import xml.etree.ElementTree as ET

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ResultadoJUnit(unittest.TextTestResult):
    """Resultado de unittest que además anota cada prueba (tiempo, fallo, omisión)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.casos = []
        self._inicio = {}

    def startTest(self, test):
        self._inicio[test.id()] = time.perf_counter()
        super().startTest(test)

    def _anotar(self, test, estado, detalle=""):
        segundos = time.perf_counter() - self._inicio.pop(test.id(), time.perf_counter())
        self.casos.append((test.id(), estado, detalle, segundos))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._anotar(test, "ok")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._anotar(test, "falla", "".join(traceback.format_exception(*err)))

    def addError(self, test, err):
        super().addError(test, err)
        self._anotar(test, "error", "".join(traceback.format_exception(*err)))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._anotar(test, "omitida", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._anotar(test, "ok")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._anotar(test, "falla", "pasó una prueba marcada como fallo esperado")


def a_xml(casos, nombre: str, segundos: float) -> ET.ElementTree:
    """Arma el XML JUnit: un <testsuite> por módulo de pruebas."""
    raiz = ET.Element("testsuites", name=nombre, time=f"{segundos:.3f}")
    suites, cuentas = {}, {}
    for ident, estado, detalle, seg in casos:
        partes = ident.split(".")
        modulo, clase, metodo = ".".join(partes[:-2]), ".".join(partes[:-1]), partes[-1]
        s = suites.get(modulo)
        if s is None:
            s = suites[modulo] = ET.SubElement(raiz, "testsuite", name=f"{nombre} · {modulo}")
            cuentas[modulo] = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time": 0.0}
        c = cuentas[modulo]
        caso = ET.SubElement(s, "testcase", classname=clase, name=metodo, time=f"{seg:.3f}")
        c["tests"] += 1
        c["time"] += seg
        if estado == "falla":
            c["failures"] += 1
            ET.SubElement(caso, "failure", message=detalle.strip().splitlines()[-1][:300]).text = detalle
        elif estado == "error":
            c["errors"] += 1
            ET.SubElement(caso, "error", message=detalle.strip().splitlines()[-1][:300]).text = detalle
        elif estado == "omitida":
            c["skipped"] += 1
            ET.SubElement(caso, "skipped", message=detalle)
    for modulo, s in suites.items():
        for k, v in cuentas[modulo].items():
            s.set(k, f"{v:.3f}" if k == "time" else str(v))
    if hasattr(ET, "indent"):          # Python 3.9+
        ET.indent(raiz)
    return ET.ElementTree(raiz)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", default="resultados-pruebas.xml", help="archivo JUnit XML a escribir")
    ap.add_argument("--nombre", default=f"Python {platform.python_version()}",
                    help="nombre del conjunto (aparece en Azure DevOps)")
    ap.add_argument("--patron", default="test_*.py")
    a = ap.parse_args(argv)

    sys.path.insert(0, RAIZ)
    suite = unittest.defaultTestLoader.discover(RAIZ, pattern=a.patron, top_level_dir=RAIZ)
    inicio = time.perf_counter()
    corredor = unittest.TextTestRunner(resultclass=ResultadoJUnit, verbosity=1, stream=sys.stdout)
    resultado = corredor.run(suite)
    segundos = time.perf_counter() - inicio

    a_xml(resultado.casos, a.nombre, segundos).write(a.salida, encoding="utf-8", xml_declaration=True)
    omitidas = sum(1 for c in resultado.casos if c[1] == "omitida")
    print(f"\n{resultado.testsRun} pruebas, {len(resultado.failures)} fallas, {len(resultado.errors)} errores, "
          f"{omitidas} omitidas -> {a.salida}")
    return 0 if resultado.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
