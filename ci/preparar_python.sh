#!/usr/bin/env bash
# Deja listo un intérprete de Python con lo que necesitan las pruebas (PyYAML) y el
# lint (pyflakes), sin tocar el Python del sistema ni el .venv del proyecto.
#
#   ci/preparar_python.sh python3.9      -> escribe la ruta del intérprete en .ci-python
#
# Lo usa azure-pipelines.yml. Prueba en orden:
#   1) un entorno virtual nuevo (.ci-venv-<versión>);
#   2) si el sistema no trae el módulo venv, instala las dependencias en .ci-libs;
#   3) si tampoco hay pip pero PyYAML ya está instalado, usa el intérprete tal cual.
# Si el intérprete pedido no existe, sale con código 3 (el pipeline lo omite con aviso).
set -euo pipefail

PEDIDO="${1:-python3}"
DEPENDENCIAS=("PyYAML==6.0.3" "pyflakes==3.2.0")

PY="$(command -v "$PEDIDO" || true)"
if [ -z "$PY" ]; then
  echo "No hay '$PEDIDO' en este agente."
  exit 3
fi
VERSION="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "Intérprete: $PY (Python $VERSION)"

VENV=".ci-venv-$VERSION"
if "$PY" -m venv "$VENV" >/dev/null 2>&1; then
  "$VENV/bin/python" -m pip install -q --disable-pip-version-check "${DEPENDENCIAS[@]}"
  echo "$PWD/$VENV/bin/python" > .ci-python
  echo "" > .ci-pythonpath
  echo "Entorno virtual listo: $VENV"
  exit 0
fi
rm -rf "$VENV"

LIBS="$PWD/.ci-libs-$VERSION"
if "$PY" -m pip --version >/dev/null 2>&1; then
  "$PY" -m pip install -q --disable-pip-version-check --target "$LIBS" "${DEPENDENCIAS[@]}"
  echo "$PY" > .ci-python
  echo "$LIBS" > .ci-pythonpath
  echo "Sin módulo venv: dependencias instaladas en $LIBS"
  exit 0
fi

if "$PY" -c 'import yaml' 2>/dev/null; then
  echo "$PY" > .ci-python
  echo "" > .ci-pythonpath
  echo "Sin venv ni pip: se usa el PyYAML ya instalado (el lint quedará omitido si falta pyflakes)."
  exit 0
fi

echo "No se pudo preparar $PY: falta el módulo venv, pip y PyYAML."
echo "En Ubuntu: sudo apt install python${VERSION}-venv"
exit 1
