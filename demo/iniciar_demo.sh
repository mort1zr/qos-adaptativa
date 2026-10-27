#!/usr/bin/env bash
# Inicia el servicio local y abre la consola de demostración.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! curl -sf http://127.0.0.1:8090/demo/estado >/dev/null; then
  sudo -v
  mkdir -p datos
  sudo nohup python3 -u demo/orquestador.py > datos/orquestador.log 2>&1 &
  listo=false
  for _ in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8090/demo/estado >/dev/null; then listo=true; break; fi
    sleep 0.5
  done
  if [ "$listo" != true ]; then
    echo 'No inició la consola. Revisa datos/orquestador.log.' >&2
    exit 1
  fi
fi
xdg-open http://127.0.0.1:8090 >/dev/null 2>&1 &
