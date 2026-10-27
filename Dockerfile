# Controlador SDN (Ryu + aplicación QoS + API + panel) en un contenedor.
#
# Qué va adentro y qué no:
#   - Adentro: el plano de control (controlador/, politicas/). Solo habla OpenFlow con
#     los switches y guarda telemetría en SQLite; no ejecuta tc ni ovs-vsctl.
#   - Afuera: Mininet/Open vSwitch (plano de datos) y la configuración de colas HTB,
#     que necesitan el kernel del host. En una empresa real pasa lo mismo: el
#     controlador corre en un servidor o en la nube y los switches están en cada sede.
#
# Construir y probar en la VM:
#   docker build -t qos-controlador .
#   docker compose up -d            # usa docker-compose.yml
#   curl http://127.0.0.1:8080/qos/estado
#
# Ryu 4.34 es de 2019: necesita Python 3.9 y setuptools < 58 para instalarse
# (la misma receta que el .venv de la VM).
FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# gcc solo para compilar la extensión de la librería ovs; se borra en la misma capa.
COPY requirements.txt .
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev \
 && pip install --upgrade pip "setuptools<58" wheel pbr \
 && pip install --no-build-isolation ryu==4.34 \
 && pip install --no-build-isolation -r requirements.txt \
 && apt-get purge -y gcc libc6-dev && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY controlador/ controlador/
COPY politicas/ politicas/

# topologia/ (inventario y roles de los switches, los escribe la topología) y datos/
# (telemetría) se montan como volúmenes. Usuario sin privilegios: uid 1000, el mismo
# que el usuario de la VM, para que los archivos de datos/ sigan siendo suyos.
RUN mkdir -p topologia datos && chown -R 1000:1000 datos
USER 1000:1000

# 6633/6653: OpenFlow (los switches se conectan aquí). 8080: API REST y panel.
EXPOSE 6633 6653 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/qos/estado', timeout=2)" || exit 1

# --wsapi-host 0.0.0.0: dentro del contenedor la API debe escuchar en todas las
# interfaces; quién puede llegar a ella lo decide la publicación de puertos
# (docker-compose.yml la limita a 127.0.0.1 de la VM).
CMD ["ryu-manager", "--wsapi-host", "0.0.0.0", "controlador/qos_app.py"]
