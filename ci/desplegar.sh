#!/usr/bin/env bash
# Despliegue continuo (la "D" de CI/CD) al laboratorio.
#
# Pone en marcha la imagen que el pipeline acaba de construir y probar como el controlador
# del laboratorio (contenedor "qos-controlador-lab"), comprueba que responda (API y panel)
# y, si no responde, vuelve a la versión anterior. Es lo que en una empresa sería desplegar
# a un ambiente de pruebas (staging) con verificación y vuelta atrás automática.
#
#   IMAGEN=qos-controlador:ci VERSION=20261026.3 ci/desplegar.sh
#
# Variables:
#   IMAGEN        imagen ya construida y probada (la etapa Contenedor)      [qos-controlador:ci]
#   VERSION       etiqueta de la versión (Azure DevOps pasa Build.BuildNumber) [local]
#   QOS_LAB_DIR   carpeta del proyecto en la VM: de ahí salen topologia/ (la escribe Mininet)
#                 y datos/ (telemetría, que también leen los escenarios)  [$HOME/qos-adaptativa]
#
# No despliega si hay una red de Mininet corriendo (un escenario o una campaña): cambiar el
# controlador en medio de una medición la arruinaría.
set -uo pipefail
cd "$(dirname "$0")/.."

IMAGEN="${IMAGEN:-qos-controlador:ci}"
VERSION="${VERSION:-${BUILD_BUILDNUMBER:-local}}"
QOS_LAB_DIR="$(printf '%s' "${QOS_LAB_DIR:-}" | xargs)"          # el pipeline manda " " si no se indicó
DESTINO="${QOS_LAB_DIR:-$HOME/qos-adaptativa}"
DESTINO="${DESTINO/#\~/$HOME}"
NOMBRE="qos-controlador-lab"
REPO="qos-controlador"
API="http://127.0.0.1:8080"

falla() { echo "##vso[task.logissue type=error]$1"; echo "ERROR: $1"; exit 1; }

command -v docker >/dev/null && docker info >/dev/null 2>&1 \
  || falla "Docker no está disponible para el usuario del agente (ver ci/README.md)."
docker image inspect "$IMAGEN" >/dev/null 2>&1 \
  || falla "No existe la imagen $IMAGEN: la etapa Contenedor no la construyó en este agente."
[ -d "$DESTINO" ] || falla "No existe la carpeta del laboratorio $DESTINO (variable QOS_LAB_DIR)."
mkdir -p "$DESTINO/datos" "$DESTINO/topologia"

if pgrep -f "^bash --norc --noediting -is mininet:" >/dev/null 2>&1; then
  falla "Hay una red de Mininet corriendo (un escenario o una campaña). No se despliega para no cortarla: vuelve a lanzar esta etapa cuando termine."
fi

corriendo="$(docker ps -q -f "name=^/${NOMBRE}$")"
if [ -z "$corriendo" ] && ss -ltn | grep -qE ':(6633|6653|8080)\s'; then
  falla "Los puertos 6633/8080 están ocupados por otro controlador (¿Ryu del .venv o docker compose?). Apágalo para desplegar."
fi

# La versión que está desplegada ahora queda guardada para poder volver a ella.
anterior=""
if docker image inspect "$REPO:lab" >/dev/null 2>&1; then
  docker tag "$REPO:lab" "$REPO:lab-anterior"
  anterior="$REPO:lab-anterior"
fi
docker tag "$IMAGEN" "$REPO:$VERSION"
docker tag "$IMAGEN" "$REPO:lab"

arrancar() {
  docker rm -f "$NOMBRE" >/dev/null 2>&1 || true
  docker run -d --name "$NOMBRE" --restart unless-stopped \
    --label "org.opencontainers.image.version=$1" \
    -p 127.0.0.1:6633:6633 -p 127.0.0.1:6653:6653 -p 127.0.0.1:8080:8080 \
    -v "$DESTINO/topologia:/app/topologia:ro" \
    -v "$DESTINO/datos:/app/datos" \
    "$REPO:lab" >/dev/null
}

responde() {
  for _ in $(seq 1 30); do
    if curl -sf -o /dev/null "$API/qos/estado" && curl -sf -o /dev/null "$API/panel"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

echo "Desplegando $REPO:$VERSION en el laboratorio ($DESTINO)…"
arrancar "$VERSION"
if responde; then
  printf '{"version": "%s", "imagen": "%s", "fecha": "%s", "destino": "%s"}\n' \
    "$VERSION" "$(docker image inspect -f '{{.Id}}' "$REPO:lab")" "$(date -Iseconds)" "$DESTINO" \
    > despliegue.json
  echo "Versión $VERSION desplegada: API y panel responden en $API/panel"
  exit 0
fi

echo "La versión $VERSION no respondió en 30 s. Últimas líneas del controlador:"
docker logs --tail 40 "$NOMBRE" 2>&1 || true
if [ -n "$anterior" ]; then
  docker tag "$anterior" "$REPO:lab"
  arrancar "anterior"
  if responde; then
    falla "La versión $VERSION no respondió; el laboratorio volvió a la versión anterior."
  fi
  falla "La versión $VERSION no respondió y la anterior tampoco: revisa 'docker logs $NOMBRE'."
fi
docker rm -f "$NOMBRE" >/dev/null 2>&1 || true
falla "La versión $VERSION no respondió y no hay una versión anterior a la que volver."
