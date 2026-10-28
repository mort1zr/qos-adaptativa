#!/usr/bin/env bash
# Prueba de integración del pipeline (solo en la VM del laboratorio):
# Mininet + Open vSwitch reales con el controlador, corriendo prueba_destinos.py (PCIII-20, ~2 min).
#
# El controlador sale de una de dos fuentes:
#   IMAGEN=qos-controlador:ci   -> la imagen de Docker que construyó el pipeline (preferida:
#                                  así se prueba el mismo contenedor que se desplegaría)
#   RYU_MANAGER=/ruta/a/.venv/bin/ryu-manager  -> el Ryu del .venv, si no hay Docker
#
# Si falta algo (sudo sin contraseña, Mininet, controlador) o el puerto 6633 ya está
# ocupado, avisa y sale con 0: la integración es opcional y no debe tumbar el build.
set -uo pipefail
cd "$(dirname "$0")/.."

aviso() { echo "##vso[task.logissue type=warning]$1"; echo "AVISO: $1"; }

if ! sudo -n true 2>/dev/null; then
  aviso "El usuario del agente no tiene sudo sin contraseña: se omite la integración (ver ci/README.md)."
  exit 0
fi
if ! command -v mn >/dev/null; then
  aviso "Mininet no está instalado en este agente: se omite la integración."
  exit 0
fi
if pgrep -f "^bash --norc --noediting -is mininet:" >/dev/null 2>&1; then
  aviso "Hay una red de Mininet corriendo (un escenario o una campaña): se omite la integración para no cortarla."
  exit 0
fi
# El controlador que dejó el despliegue (ci/desplegar.sh) se pausa durante la prueba y se
# vuelve a levantar al final, pase lo que pase.
LAB_PAUSADO=""
if command -v docker >/dev/null && [ -n "$(docker ps -q -f 'name=^/qos-controlador-lab$' 2>/dev/null)" ]; then
  echo "Se pausa el controlador del laboratorio (qos-controlador-lab) durante la prueba."
  docker stop qos-controlador-lab >/dev/null && LAB_PAUSADO=1
  trap 'docker start qos-controlador-lab >/dev/null 2>&1 || true' EXIT
fi
if ss -ltn | grep -qE ':(6633|8080)\s'; then
  aviso "Ya hay algo escuchando en 6633/8080 (¿tu Ryu o docker compose?). Apágalo para correr la integración."
  exit 0
fi

mkdir -p datos topologia experimentos/resultados
MODO=""
if [ -n "${IMAGEN:-}" ] && command -v docker >/dev/null && docker image inspect "$IMAGEN" >/dev/null 2>&1; then
  MODO="contenedor"
  docker rm -f qos-ci >/dev/null 2>&1 || true
  docker run -d --name qos-ci \
    -p 127.0.0.1:6633:6633 -p 127.0.0.1:8080:8080 \
    -v "$PWD/topologia:/app/topologia:ro" -v "$PWD/politicas:/app/politicas:ro" -v "$PWD/datos:/app/datos" \
    "$IMAGEN" >/dev/null
elif [ -n "${RYU_MANAGER:-}" ] && [ -x "$RYU_MANAGER" ]; then
  MODO="venv"
  "$RYU_MANAGER" controlador/qos_app.py > ryu-ci.log 2>&1 &
  PID_RYU=$!
else
  aviso "No hay controlador para la integración (ni imagen '$IMAGEN' ni RYU_MANAGER): se omite."
  exit 0
fi
echo "Controlador: $MODO"

terminar() {
  sudo -n mn -c >/dev/null 2>&1 || true
  if [ "$MODO" = "contenedor" ]; then
    docker logs qos-ci > ryu-ci.log 2>&1 || true
    docker rm -f qos-ci >/dev/null 2>&1 || true
  else
    kill "$PID_RYU" 2>/dev/null || true
  fi
  # Lo que escribió sudo (CSV, inventario) vuelve al usuario del agente.
  sudo -n chown -R "$(id -u):$(id -g)" datos topologia experimentos/resultados 2>/dev/null || true
  if [ -n "$LAB_PAUSADO" ]; then
    docker start qos-controlador-lab >/dev/null 2>&1 || true
  fi
}
trap terminar EXIT

for _ in $(seq 1 30); do
  curl -sf -o /dev/null http://127.0.0.1:8080/qos/estado && break
  sleep 1
done
if ! curl -sf -o /dev/null http://127.0.0.1:8080/qos/estado; then
  echo "El controlador no respondió en 30 s."
  exit 1
fi
curl -sf -o /dev/null http://127.0.0.1:8080/panel && echo "Panel: OK"

sudo -n python3 experimentos/prueba_destinos.py --sala 1 --datapath "${DATAPATH:-kernel}"
CODIGO=$?
echo "prueba_destinos.py terminó con código $CODIGO"
exit $CODIGO
