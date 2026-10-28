#!/usr/bin/env bash
# Construye la imagen del controlador y le hace una prueba de humo:
# el contenedor arranca, responde la API (/qos/estado) y sirve el panel (/panel).
#
#   IMAGEN=qos-controlador:ci ci/imagen.sh
#
# Si el agente no tiene Docker (o el usuario no está en el grupo docker), avisa y sale
# con 0: el resto del pipeline sigue. No sube la imagen a ningún registro (eso necesita
# Azure Container Registry, es decir, una suscripción; ver ci/README.md).
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGEN="${IMAGEN:-qos-controlador:ci}"
PRUEBA="qos-humo-$$"
PUERTO="${PUERTO_HUMO:-18080}"

aviso() { echo "##vso[task.logissue type=warning]$1"; echo "AVISO: $1"; }

if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then
  aviso "Docker no está disponible para el usuario del agente: se omite la imagen (ver ci/README.md)."
  echo "##vso[task.setvariable variable=HAY_IMAGEN;isOutput=true]false"
  exit 0
fi

docker build --pull \
  --label "org.opencontainers.image.revision=${BUILD_SOURCEVERSION:-local}" \
  --label "org.opencontainers.image.source=https://github.com/mort1zr/qos-adaptativa" \
  -t "$IMAGEN" .

limpiar() { docker rm -f "$PRUEBA" >/dev/null 2>&1 || true; }
trap limpiar EXIT
docker run -d --name "$PRUEBA" -p "127.0.0.1:$PUERTO:8080" "$IMAGEN" >/dev/null

for _ in $(seq 1 30); do
  curl -sf -o /dev/null "http://127.0.0.1:$PUERTO/qos/estado" && break
  sleep 1
done
if ! curl -sf "http://127.0.0.1:$PUERTO/qos/estado" > estado-contenedor.json; then
  echo "El contenedor no respondió en 30 s. Registro:"
  docker logs "$PRUEBA" || true
  exit 1
fi
curl -sf -o /dev/null "http://127.0.0.1:$PUERTO/panel"
echo "Contenedor OK: API y panel responden."
docker image ls "$IMAGEN" --format 'Imagen {{.Repository}}:{{.Tag}} · {{.Size}}'
echo "##vso[task.setvariable variable=HAY_IMAGEN;isOutput=true]true"
