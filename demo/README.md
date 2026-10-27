# Consola de demostración

La consola reúne Demo, Topología, Tráfico y Evidencias en
`http://127.0.0.1:8090`. El orquestador y los puertos publicados por Docker se
mantienen en localhost. Las acciones usan comandos fijos y parámetros validados.

## Revisar la interfaz sin herramientas de red

Desde la raíz del proyecto:

```bash
python3 demo/orquestador.py --vista-previa
```

Abre `http://127.0.0.1:8090`. Este modo bloquea las acciones y los cambios de
clasificador. No simula resultados ni levanta la red; permite revisar la interfaz
sin root. Si hay mediciones previas en `datos/progreso.json`, las muestra como
resultados guardados. Ctrl+C cierra el servidor.

## Ejecutar la demo real

Requiere la VM del laboratorio con Mininet, Open vSwitch, tc, iperf3, PyYAML y
Ryu en Python 3.9 o Docker. No basta con abrir el HTML ni con instalar Docker.
Verifica también los módulos del kernel de la especificación.

1. Revisa `demo/demo.yaml`:
   - `lab`: usa el contenedor `qos-controlador-lab` creado por el pipeline.
     Esa imagen debe incluir esta actualización, con las nuevas rutas de API;
     una imagen anterior no entregará topología ni progreso.
   - `docker`: usa `docker compose up -d` en esta copia del proyecto.
   - `venv`: usa `.venv/bin/ryu-manager` como tu usuario normal, mediante sudo.
2. No dejes otra topología ni otro controlador ocupando los puertos del laboratorio.
   Para elegir Docker sin modificar la configuración guardada, también puedes
   iniciar con `sudo python3 demo/orquestador.py --controlador docker`.
3. Ejecuta `demo/iniciar_demo.sh`. Pide sudo una vez y abre la consola.
4. Inicia el controlador, levanta la red y explora la topología y las evidencias.
5. Ejecuta un escenario o compara dos estrategias. El escenario sustituye a la
   red en reposo y escribe `experimentos/resultados/demo.csv` y
   `demo_contexto.csv`; el progreso está en `datos/progreso.json`.

El panel original sigue en `http://127.0.0.1:8080/panel`. En la consola se sirve
desde `/panel?demo=1` y bloquea el cambio manual de clasificador durante un
escenario. El servidor también lo impide, independientemente del estado del botón.

No abras el puerto 8090 en la red. Para acceso remoto usa el túnel SSH indicado
en la especificación. No publiques nuevos cambios en main durante una medición.

## Acceso directo

```bash
python3 demo/instalar_acceso.py
```

Esto regenera `demo/QoS-Demo.desktop` con la ruta de esta copia del repositorio.
Cópialo a tu escritorio y habilita su ejecución desde el gestor de archivos si
Ubuntu lo solicita. Regénéralo si cambias de carpeta. No ejecuta la demo por sí solo.

## Pruebas

```bash
python3 -m unittest discover -p 'test_*.py'
python3 ci/pruebas_junit.py --salida resultados-pruebas-demo.xml
python3 -m pyflakes controlador escenarios trafico experimentos politicas topologia ci demo
```

Las nuevas pruebas de HTTP abren puertos aleatorios en localhost; no requieren
root, Docker ni Mininet. Las pruebas de estados y comandos usan ejecutores falsos.
No reemplazan la lista manual 6.2 de `docs/ESPECIFICACION_DEMO.md`.

## Decisiones respecto de la especificación

- Sin `--salida` se conserva `datos/contexto.csv`, que es la ruta real de las
  campañas existentes. Con `--salida`, el contexto va junto al CSV con sufijo
  `_contexto.csv`. No se cambia `correr_fase()` ni las políticas.
- La evidencia de Controller consulta `target,is_connected`: OVS usa `target`
  para la dirección del controlador; la columna `name` indicada en el documento
  no corresponde a esa tabla.
- La respuesta de telemetría conserva las doce áreas destacadas del panel y
  agrega `areas_completas` para no perder segmentos en el mapa.
- Se rechazan las acciones si se detecta una red de Mininet ajena a esta consola.
  La limpieza de una red propia puede reiniciar el Ryu del modo venv.
- La duración es orientativa: además de las fases hay armado, calentamiento,
  espera de sondas y telemetría. No se garantiza el tiempo del guion sin medirlo
  en la VM real.

## Validación pendiente en el laboratorio

En el entorno de desarrollo faltan Mininet, OVS, Docker y Ryu, y sudo requiere una
contraseña interactiva que no está disponible para esta ejecución. Por ello no se ha verificado aquí el arranque real,
44 switches conectados, contadores HTB, recuperación tras una cancelación con
procesos reales ni la comparación de calidad de voz. Ningún resultado de ejemplo
se presenta como medición real. Usa la lista 6.2 antes de presentar la demo.
