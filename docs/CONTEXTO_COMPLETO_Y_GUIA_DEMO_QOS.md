# Proyecto QoS adaptativa: contexto completo, operación, pruebas y sustentación

**Documento preparado el 26 de octubre de 2026 para conservar el contexto de esta sesión.**

Este documento reúne lo que se encontró, lo que se incorporó y programó, cómo se instaló y ejecutó el laboratorio, los resultados reales obtenidos y cómo practicar y presentar la demo. También explica qué se puede modificar y qué se confirmó en GitHub.

## Lectura rápida: en qué estado quedó el proyecto

- El laboratorio **ya se ejecutó con tráfico real en este Ubuntu**; la página dejó de ser únicamente una vista previa.
- El controlador Ryu funciona dentro de Docker. Mininet, Open vSwitch y las colas de Linux funcionan en el host Ubuntu.
- Se verificaron **44 de 44 switches conectados**, cinco sedes y **276 equipos del inventario**, de los cuales ocho representan servidores de Internet dentro de la simulación.
- La comparación `respaldo_en_atencion`, Sala 1, `sin_qos` frente a `prioridad`, terminó con **seis fases válidas**.
- En su fase de respaldo, la voz p95 pasó de **394,24 ms a 13,97 ms**; pagos, de **850,3 ms a 29,2 ms**; web, de **5778,8 ms a 1051,8 ms**.
- Se hicieron **187 pruebas de código: 186 correctas y una omitida**. La omitida requiere ejecutarse con sudo. La revisión con pyflakes no encontró avisos.
- Los resultados de demostración se guardan separados de los resultados históricos de la tesis.
- La IA todavía está pendiente. Los resultados actuales corresponden a políticas, clasificación por destino y colas.
- Se incorporó código de CI/CD para Azure DevOps, pero **no se comprobó una ejecución del pipeline en Azure DevOps**.
- Todo el código desarrollado e integrado quedó publicado en **`demo-consola`**, con seis commits sobre la base original. Este documento se incorpora después en un séptimo commit de documentación.
- **No se modificó ni se fusionó nada en `main`.**

**Estado observado al preparar este documento:** consola real en `http://127.0.0.1:8090`, controlador en línea, modo `docker`, red en reposo levantada y 44 switches conectados. Esto puede cambiar si se cierra la terminal del servidor, se apaga la VM o se accionan los botones.

## Índice

1. [Propósito del proyecto y alcance actual](#1-propósito-del-proyecto-y-alcance-actual)
2. [Punto de partida: repositorio, ZIP y especificación](#2-punto-de-partida-repositorio-zip-y-especificación)
3. [Arquitectura y recorrido de una operación](#3-arquitectura-y-recorrido-de-una-operación)
4. [Todo lo que se hizo durante la sesión](#4-todo-lo-que-se-hizo-durante-la-sesión)
5. [Archivos y módulos que debes conocer](#5-archivos-y-módulos-que-debes-conocer)
6. [Cómo acceder y arrancar el entorno](#6-cómo-acceder-y-arrancar-el-entorno)
7. [Cómo practicar con la página](#7-cómo-practicar-con-la-página)
8. [Cómo repetir las pruebas y conservar resultados](#8-cómo-repetir-las-pruebas-y-conservar-resultados)
9. [Resultados reales y límites de lo comprobado](#9-resultados-reales-y-límites-de-lo-comprobado)
10. [Qué mostrar y cómo explicarlo al profesor](#10-qué-mostrar-y-cómo-explicarlo-al-profesor)
11. [Cómo variar políticas, escenarios y topología](#11-cómo-variar-políticas-escenarios-y-topología)
12. [Solución de problemas](#12-solución-de-problemas)
13. [GitHub: commits, rama y confirmación sobre main](#13-github-commits-rama-y-confirmación-sobre-main)
14. [Glosario y preguntas probables](#14-glosario-y-preguntas-probables)
15. [Archivos de respaldo y contexto para continuar](#15-archivos-de-respaldo-y-contexto-para-continuar)

---

## 1. Propósito del proyecto y alcance actual

### 1.1 El problema

Una empresa tiene aplicaciones que compiten por enlaces con capacidad limitada. Una descarga grande o un respaldo pueden aumentar los tiempos de respuesta de llamadas, pagos y páginas web. El proyecto estudia cómo administrar ese tráfico con SDN y QoS.

La QoS **no crea más capacidad de Internet**. Define cómo se distribuyen los recursos y cómo se atienden los paquetes. Por ejemplo, una llamada puede recibir un tratamiento distinto al de una descarga.

### 1.2 Qué hay implementado

El repositorio ya contenía la red empresarial, clasificación, políticas, colas, generación de tráfico y experimentos. Durante esta sesión se incorporó el paquete adicional del Sprint 3 y se implementó una consola para coordinar y observar ese laboratorio.

Actualmente se puede:

- Crear la red virtual empresarial.
- Conectar los switches al controlador Ryu.
- Usar estrategias de referencia y de prioridad.
- Generar tráfico de laboratorio y ejecutar sondas.
- Medir voz, video, pagos, web y otros indicadores.
- Consultar telemetría y reglas reales de los switches.
- Manejar la demostración desde una consola con cuatro pestañas.
- Comparar dos estrategias y mostrar resultados por fase.

### 1.3 Qué sigue pendiente

- Entrenar y evaluar los modelos de IA previstos para los siguientes sprints.
- Demostrar el funcionamiento del pipeline en una organización de Azure DevOps.
- Completar todos los casos manuales de aceptación, especialmente cancelaciones de escenarios a mitad de fase y recuperación de todos los fallos posibles.
- Hacer campañas repetidas para extraer conclusiones estadísticas generales.

El nombre global del proyecto incluye QoS adaptativa e IA, pero en la sustentación debes distinguir ese objetivo final de la implementación actual.

## 2. Punto de partida: repositorio, ZIP y especificación

### 2.1 Repositorio

Repositorio de origen:

<https://github.com/mort1zr/qos-adaptativa>

La copia local se creó desde `main`, cuya base era:

```text
86782458ae549a68a46e92102a7c8959065a6ddc
```

Después se creó la rama `demo-consola` antes de integrar y desarrollar los cambios.

### 2.2 Paquete del Sprint 3

Se revisaron los adjuntos `sprint3-azure-cicd.zip` y `ESPECIFICACION_DEMO.md`. El ZIP contenía **18 archivos**, no el repositorio completo. La copia de la especificación dentro del ZIP era idéntica al archivo Markdown externo.

Contenido del ZIP:

```text
.dockerignore
.gitignore
Dockerfile
azure-pipelines.yml
ci/README.md
ci/desplegar.sh
ci/imagen.sh
ci/integracion.sh
ci/preparar_python.sh
ci/pruebas_junit.py
controlador/panel/index.html
controlador/qos_app.py
controlador/telemetria.py
controlador/test_telemetria.py
docker-compose.yml
docs/ESPECIFICACION_DEMO.md
experimentos/prueba_destinos.py
politicas/cargador.py
```

Faltaban en ese ZIP módulos esenciales, como los clasificadores, inventario, topología, escenarios y los YAML. Por eso primero fue necesario descargar el repositorio completo y después integrar el paquete.

### 2.3 Lo que proponía la especificación

La especificación planteaba una consola nueva, en el puerto 8090, para iniciar y detener el controlador, levantar la red, ejecutar escenarios, ver la topología y consultar evidencias sin abrir varias terminales durante la exposición.

La consola no estaba implementada en el ZIP. El panel de tráfico y los scripts de CI/CD sí estaban incluidos como código para integrar.

### 2.4 Distinción de autoría

La red, políticas, escenarios y mecanismos de QoS existían previamente en el trabajo del equipo. El paquete del Sprint 3 se incorporó desde el ZIP proporcionado. La consola y sus integraciones se desarrollaron durante esta sesión con asistencia de IA.

No debes atribuir toda la red ni todo el Sprint 3 a una sola sesión o persona. Para sustentar con transparencia, explica el trabajo previo del equipo y la asistencia utilizada para ampliar y probar la consola.

## 3. Arquitectura y recorrido de una operación

### 3.1 Esquema general

```text
Navegador dentro de Ubuntu
http://127.0.0.1:8090
             |
             v
Orquestador de demo — Python del sistema, con privilegios
  - Sirve la página y recibe acciones validadas
  - Coordina controlador, red y escenarios
  - Consulta evidencias de OVS y Linux
  - Reenvía las consultas /qos/* a Ryu
             |
       +-----+---------------------+
       |                           |
       v                           v
Ryu en Docker                Mininet en Ubuntu
controlador/qos_app.py        topologia/empresa_xyz.py
API y panel :8080            Hosts, routers y switches OVS
       |                           |
       +-------- OpenFlow ---------+
                                   |
                         Colas HTB y herramientas tc
                                   |
                         Tráfico y sondas de escenarios
                                   |
                  SQLite, progreso JSON y resultados CSV
```

### 3.2 Qué hace cada componente

| Componente | Responsabilidad |
|---|---|
| Mininet | Crea equipos, interfaces, enlaces y espacios de red virtuales. |
| Open vSwitch | Reenvía paquetes siguiendo reglas OpenFlow. |
| Ryu | Clasifica flujos e instala reglas en los switches. |
| OpenFlow 1.3 | Comunica reglas y estadísticas entre Ryu y los switches. |
| Colas HTB | Aplican garantías, techos y prioridades de ancho de banda. |
| Generadores y sondas | Producen tráfico y miden resultados de laboratorio. |
| Telemetría | Calcula tasas y guarda contadores y decisiones en SQLite. |
| Orquestador | Coordina procesos del laboratorio desde acciones fijas. |
| Consola | Muestra estados, permite ejecutar acciones y presenta resultados. |
| Docker | Aísla el entorno Python 3.9/Ryu del controlador. |
| Azure DevOps | Tiene código preparado para automatizar pruebas, imagen y despliegue. |

**Docker contiene el controlador. Mininet y OVS funcionan en el host Ubuntu.** No se trasladó toda la red al contenedor.

### 3.3 Recorrido de un clic

Al pulsar Comparar:

1. El navegador envía el nombre del escenario, las estrategias, sala y velocidad.
2. El orquestador valida que los valores estén permitidos.
3. Si hay una red en reposo, la detiene; el escenario construye su propia red.
4. Inicia `escenarios/escenario.py` con argumentos concretos.
5. El escenario configura las colas y el clasificador según cada estrategia.
6. Los generadores producen tráfico y las sondas realizan las mediciones.
7. Al comenzar y terminar cada fase se actualiza el progreso JSON.
8. La consola consulta el progreso y llena las tablas con esas mediciones.
9. El escenario guarda CSV separados y limpia su red al terminar.

### 3.4 Recorrido de un flujo

1. El clasificador determina la clase del flujo.
2. Ryu obtiene la cola correspondiente.
3. Instala una regla con una acción `set_queue:N` y un puerto de salida.
4. OVS aplica la regla a los paquetes que coinciden.
5. La disciplina de colas distribuye los recursos configurados.

Para destinos conocidos también hay reglas anticipadas, identificadas con cookie `0x20`. Las reglas por flujo usan cookie `0x16`. La copia inicial al controlador permite crear el registro del flujo sin perder su telemetría.

### 3.5 Topología comprobada

| Sede | Equipos del inventario | Capacidad de acceso configurada |
|---|---:|---:|
| Oficina central | 30 | 50 Mbps |
| Sala 1 | 74 | 30 Mbps |
| Sala 2 | 64 | 20 Mbps |
| Sala 3 | 57 | 20 Mbps |
| Sala 4, provincia | 43 | 10 Mbps |
| Servidores que representan Internet | 8 | No es una sexta sede |
| **Total** | **276** | |

Se verificaron **44 switches**. Los 276 equipos son entradas del inventario; los procesos de routers y otros componentes del laboratorio no deben confundirse con ese conteo.

Sala 1 tiene seis segmentos: máquinas, administración, pagos, CCTV, WiFi personal y WiFi clientes. Sus 74 equipos se distribuyen en 33, 6, 2, 25, 2 y 6, respectivamente.

### 3.6 Puertos

| Puerto | Uso |
|---|---|
| 8090 | Consola y API del orquestador. |
| 8080 | API de Ryu y panel antiguo `/panel`. |
| 6633 | Puerto de OpenFlow al que se conecta la topología. |
| 6653 | También publicado por la configuración Docker. |

Las publicaciones de Docker se limitan a `127.0.0.1`, y la consola escucha en esa dirección local.

## 4. Todo lo que se hizo durante la sesión

### 4.1 Inspección inicial

- Se recuperaron los dos adjuntos de la conversación anterior.
- Se enumeraron los 18 archivos del ZIP y se leyeron sus componentes principales.
- Se distinguió el código existente de las propuestas del documento.
- Se identificó que el ZIP no era autosuficiente y necesitaba el repositorio base.
- Se explicaron riesgos, como pruebas que podían omitirse, imagen local entre etapas del pipeline y diferencias entre integración y despliegue.

### 4.2 Descarga e integración

- Se clonó el repositorio de GitHub.
- Se verificó la base `8678245` de `main`.
- Se creó `demo-consola` para trabajar separado de `main`.
- Se integró el paquete del Sprint 3: panel, mejoras de telemetría, Docker, CI/CD y especificación.
- Los scripts `.sh` de CI recibieron permisos de ejecución.
- Se creó documentación para abrir y trabajar el proyecto desde VS Code.

El primer conjunto de pruebas del repositorio tenía 151 casos, con diez omisiones en aquel entorno. Después de integrar el ZIP se ejecutaron 155, también con diez omisiones. Las cifras finales aumentaron con las pruebas nuevas y con la instalación de OVS.

### 4.3 Progreso y separación de resultados

Se añadió `escenarios/progreso.py` y se amplió `escenarios/escenario.py` con:

- `--progreso`: publica estados pendientes, corriendo y terminados, métricas, cumplimiento, validez y errores.
- `--salida`: permite guardar resultados de demostración en otro CSV.
- Escritura atómica del progreso: archivo temporal y reemplazo, para evitar JSON parcialmente escrito.
- Tratamiento de señales en la demo para recorrer la limpieza al cancelar.

La función `correr_fase()`, que realiza las mediciones, no se cambió para producir números más favorables. El progreso utiliza las filas que ya generan las mediciones.

**Compatibilidad conservada:** sin `--salida`, el contexto sigue en `datos/contexto.csv`, que era la ruta real del código. Con `--salida`, el contexto queda junto al resultado con sufijo `_contexto.csv`.

### 4.4 Red en reposo y API de topología

- Se añadió `--esperar` a la topología para mantenerla levantada sin abrir la CLI de Mininet.
- Se protegió la limpieza también ante una interrupción durante el armado.
- Se creó `controlador/topologia.py` para describir sedes, segmentos, equipos y switches desde los inventarios.
- Se añadieron `/qos/topologia` y `/qos/progreso`.
- El estado del controlador empezó a informar de todos los switches conectados y del total esperado.
- La telemetría mantuvo las doce áreas destacadas del panel y agregó `areas_completas` para el mapa.

### 4.5 Orquestador y consola

Se implementaron:

- Control del controlador en modos `lab`, `venv` y `docker`.
- Una sola tarea pesada de red o escenario a la vez.
- Validación de escenarios, estrategias, salas y velocidad.
- Subprocesos con listas de argumentos y grupos de procesos.
- Cancelación, limpieza, registro de actividad y devolución al usuario de archivos creados con sudo.
- Consultas de evidencias mediante comandos definidos, con tiempos máximos.
- Reenvío de las rutas de API permitidas.
- Rechazo de orígenes y hosts ajenos al acceso local previsto.
- Vista previa sin privilegios, con acciones bloqueadas.
- Una consola sin dependencias de CDN, con Demo, Topología, Tráfico y Evidencias.
- Bloqueo del cambio manual de clasificador durante escenarios, tanto en la interfaz como en el servidor.
- Un acceso directo y un generador para adaptarlo a la ubicación real del proyecto.

Durante la revisión del navegador se corrigió un encabezado que inicialmente impedía incrustar el panel de Tráfico. Se permite ahora su uso desde el mismo origen.

### 4.6 Pruebas de código

Se añadieron pruebas de:

- Escritura y transiciones del progreso.
- Salida de demo separada y conservación de las rutas habituales.
- Topología e inventarios pequeños, islas y conectividad.
- Validación de acciones y rechazo de parámetros inválidos.
- Estados incompatibles y una acción a la vez.
- Comandos sin ejecución real mediante dobles de prueba.
- Cancelación y señales simuladas.
- Reenvío HTTP, bloqueo de clasificador y acceso local.
- Red en espera y limpieza con un Mininet falso.
- Elección de modo Docker sin modificar la configuración guardada.

También se revisó sintaxis Python, JavaScript y Bash, y se ejecutó pyflakes.

### 4.7 Instalación en este Ubuntu

El usuario ejecutó el instalador preparado con sudo desde su terminal. Se instalaron o verificaron:

```text
mininet
openvswitch-switch
iperf3
iproute2
docker.io
docker-compose-v2
python3-yaml
python3.10-venv
curl
```

Se cargaron `openvswitch`, `sch_htb`, `sch_netem` e `ifb`, y se iniciaron los servicios de OVS y Docker.

Entorno observado:

- Ubuntu 22.04.5 LTS en VirtualBox.
- Kernel 6.8.0-138-generic.
- Tres CPU virtuales y aproximadamente 4 GB de RAM.
- Python del sistema 3.10.
- Docker 29.1.3 y Compose 2.40.3.
- Ryu 4.34 con Python 3.9 dentro del contenedor.

La autorización de sudo de la terminal del usuario no se comparte automáticamente con los procesos de las herramientas del asistente. Por eso el usuario ejecutó un segundo script que construyó Docker y mantuvo abierto el orquestador real con privilegios.

No se configuró sudo sin contraseña ni se cambió el usuario para darle acceso general al grupo Docker.

### 4.8 Construcción y primer arranque real

- Se verificó que las versiones declaradas de las dependencias admitieran Python 3.9.
- Se construyó `qos-controlador:local` con el Dockerfile.
- Se inició el contenedor `qos-controlador` con Docker Compose.
- Se comprobaron las respuestas de la API y de la nueva ruta de topología.
- Se inició el orquestador en modo real con `--controlador docker`.
- Se levantó la red desde la consola y se verificó 44/44.
- Se activó la clasificación por destino y se consultaron las cuatro evidencias.
- En Sala 1 se observaron 346 reglas anticipadas con `set_queue` y cookie `0x20`.
- Se observaron clases HTB y configuración `linux-htb` en los accesos.

### 4.9 Pruebas reales de tráfico

Se ejecutaron dos experimentos:

1. `enlace_degradado`, prioridad, Sala 1, rápido: tres fases. Dos válidas y una recuperación inválida por CPU alta.
2. `respaldo_en_atencion`, `sin_qos` y `prioridad`, Sala 1, duración completa: seis fases, todas válidas.

Se conservaron nueve filas de resultados de demo. No se borró la fila inválida ni se ajustaron criterios para convertirla en válida.

Se verificó por hashes que 17 archivos rastreados de resultados históricos y políticas permanecieran iguales después de las corridas. Esto se refiere a los datos históricos y reglas comprobados; `politicas/cargador.py` sí tuvo una limpieza previa de un import no utilizado al integrar el ZIP, sin modificar las reglas YAML.

### 4.10 Ajustes posteriores a la prueba real

Se ajustó la interfaz para:

- Mostrar la red conectada durante el escenario.
- Calcular el uso respecto de la capacidad disponible durante una degradación.
- Evitar usar muestras del enlace anteriores al comienzo de la fase degradada.
- Recuperar las selecciones al recargar, incluso a partir de los parámetros guardados del último progreso.
- Evitar mostrar el reloj de un escenario anterior mientras empieza otro.
- Conservar los valores de una fase inválida sin pintarlos con marcas de cumplimiento.
- Indicar que la demanda por segmentos corresponde a dos minutos y mostrar más decimales en tráfico pequeño.
- Expresar la duración aproximada por estrategia, porque comparar ejecuta dos estrategias.

Finalmente se volvió a levantar la red en reposo, se guardaron evidencias y documentación, y se publicaron los cambios en la misma rama de GitHub.

## 5. Archivos y módulos que debes conocer

### 5.1 Mapa del proyecto

```text
qos-adaptativa/
  Dockerfile
  docker-compose.yml
  azure-pipelines.yml
  requirements.txt
  ci/                       scripts y documentación de CI/CD
  controlador/
    qos_app.py              aplicación Ryu y API REST
    clasificadores.py       ninguno, politica y destino
    inventario.py           lectura y recarga de inventarios
    colas.py                configuración HTB mediante OVS y tc
    estatica.py             cambios de techos según horario
    telemetria.py           mediciones y SQLite
    topologia.py            estructura de topología y lectura de progreso
    api.py                  cliente de API para escenarios/terminal
    panel/index.html        panel de tráfico existente
  demo/
    orquestador.py          servidor y coordinación de acciones
    demo.yaml               configuración del orquestador
    consola/index.html      página de cuatro pestañas
    iniciar_demo.sh         arranque según configuración guardada
    instalar_acceso.py      genera el acceso directo con ruta real
    QoS-Demo.desktop        acceso directo generado
    README.md               uso y límites de la consola
    test_*.py               pruebas de orquestador y red en espera
  escenarios/
    escenario.py            planifica, ejecuta y registra escenarios
    escenarios.yaml         situaciones, fases y objetivos de pagos/web
    operador.py             degradación del enlace del operador
    reloj.py                tiempo simulado
    progreso.py             publicación de fases para la consola
  topologia/
    empresa_xyz.py          construcción de la red
    empresa_xyz.yaml        sedes, equipos, enlaces y direccionamiento
    inventario.csv          generado al levantar la red
    switches.csv            generado al levantar la red
  politicas/
    politicas.yaml          clases, garantías, techos y reglas
    destinos.yaml           destinos conocidos
    horario.yaml            estrategia estática por horario
    cargador.py             carga y validación
  trafico/
    perfiles.yaml           perfiles e intensidades de tráfico
    generador.py             inicia los procesos de tráfico
    aplicaciones.py         clientes, servidores y tráfico sintético
  experimentos/
    medicion.py             herramientas de medición de las sondas
    prueba_destinos.py       comprobación específica de destinos
    resultados/             históricos y CSV de demo ignorados por Git
  datos/                    SQLite, reloj, progreso y registros locales
  docs/
    ESPECIFICACION_DEMO.md
    DESARROLLO_LOCAL.md
    VALIDACION_LOCAL.md
```

### 5.2 Qué leer primero para responder preguntas de código

1. `demo/orquestador.py`: acciones y validación de entradas.
2. `escenarios/escenario.py`: `poner_estrategia()`, `ejecutar()` y `correr_fase()`.
3. `controlador/qos_app.py`: decisiones, reglas anticipadas y `acciones_flujo()`.
4. `controlador/clasificadores.py`: criterio de clasificación.
5. `controlador/colas.py`: garantías, techos, prioridad y filas de espera.
6. `controlador/telemetria.py`: cómo se calculan las tasas a partir de contadores.
7. `topologia/empresa_xyz.py`: construcción y configuración de la red.

### 5.3 API principal

Consultas de Ryu:

```text
GET       /qos/estado
GET       /qos/telemetria
GET       /qos/serie
GET       /qos/topologia
GET       /qos/progreso
PUT/POST  /qos/clasificador   (en Ryu)
GET       /panel
```

La consola reenvía GET de las rutas permitidas y PUT de clasificador. Las acciones de red del orquestador incluyen iniciar/detener controlador y red, ejecutar escenario, cancelar, limpiar y consultar evidencias.

No existe una ruta para introducir y ejecutar comandos arbitrarios del usuario.

## 6. Cómo acceder y arrancar el entorno

### 6.1 Carpeta exacta de esta copia

```text
/home/elonmusk/Documents/Codex/2026-10-26/referenced-chatgpt-conversation-this-is-an/qos-adaptativa
```

En los comandos siguientes, entra primero allí:

```bash
cd "/home/elonmusk/Documents/Codex/2026-10-26/referenced-chatgpt-conversation-this-is-an/qos-adaptativa"
```

Si abres VS Code, usa Archivo → Abrir carpeta y selecciona esa carpeta raíz. Si tienes disponible `code`, desde allí puedes ejecutar `code .`. Mantén el editor como usuario normal.

### 6.2 Si la consola sigue encendida

Abre el navegador **dentro de Ubuntu** y visita:

<http://127.0.0.1:8090>

El panel antiguo está en:

<http://127.0.0.1:8080/panel>

`127.0.0.1` significa la misma máquina desde la cual abres el navegador. Si abres esa dirección en Windows fuera de la VM, estarás buscando un servidor en Windows, no dentro de Ubuntu. Para la presentación, abre el navegador en Ubuntu.

No necesitas conexión a Internet para cargar los recursos de la consola y generar el tráfico interno una vez que las herramientas y la imagen Docker están disponibles. La instalación, la primera construcción de la imagen y el acceso a GitHub sí utilizaron Internet.

### 6.3 Arranque sencillo en este mismo equipo

El script de arranque real quedó fuera del repositorio, en la carpeta de entregables:

```bash
sudo bash "/home/elonmusk/Documents/Codex/2026-10-26/referenced-chatgpt-conversation-this-is-an/outputs/iniciar-demo-real.sh"
```

Este script:

1. Comprueba que se ejecute con privilegios.
2. Comprueba que no haya otra consola respondiendo en 8090 ni otra red de Mininet detectada.
3. Prepara el directorio y registro de arranque.
4. Construye o reutiliza las capas de la imagen Docker.
5. Inicia el controlador con Compose.
6. Espera que la API responda y verifica la ruta de topología.
7. Ejecuta el orquestador en primer plano con `--controlador docker`.

**Deja esa terminal abierta.** Es la terminal del servidor, no una terminal en la que debas seguir escribiendo comandos. Para otros comandos usa una segunda terminal.

Si ya existe una consola en 8090, el script no inicia otra. Usa la consola existente o detén ordenadamente la anterior.

### 6.4 Arranque manual equivalente

Desde la raíz del repositorio:

```bash
mkdir -p datos
sudo systemctl start openvswitch-switch docker
sudo docker compose build
sudo docker compose up -d --no-build
curl -fsS http://127.0.0.1:8080/qos/estado
sudo python3 -u demo/orquestador.py --controlador docker
```

La última línea mantiene el servidor en esa terminal. Después abre `http://127.0.0.1:8090` en el navegador.

En un arranque posterior a reiniciar Ubuntu, si necesitas verificar los módulos:

```bash
sudo modprobe openvswitch
sudo modprobe sch_htb
sudo modprobe sch_netem
sudo modprobe ifb
```

El controlador se inicia con Docker y la red se levanta después desde el botón de la consola. No ejecutes dos controladores intentando usar simultáneamente 6633 y 8080.

### 6.5 Diferencia importante entre los modos

| Modo | Qué utiliza | Situación en esta sesión |
|---|---|---|
| `docker` | Contenedor `qos-controlador` de Docker Compose. | **Modo utilizado y probado.** |
| `lab` | Contenedor `qos-controlador-lab` creado por el pipeline. | No se verificó ese despliegue aquí. |
| `venv` | Ryu de `.venv/bin/ryu-manager` como usuario normal. | No se preparó este entorno alternativo aquí. |

`demo/demo.yaml` conserva `controlador: lab` como valor de la especificación. Por eso, en este equipo usamos **`--controlador docker`**, que lo sobreescribe sin editar el archivo.

No uses `demo/iniciar_demo.sh` esperando que elija automáticamente Docker: usa la configuración guardada. Si quieres usar ese arranque y el acceso directo en este equipo, cambia conscientemente `controlador: lab` por `controlador: docker` en `demo/demo.yaml` y vuelve a iniciar el orquestador. Como es un archivo rastreado, ese cambio aparecerá en `git status`.

### 6.6 Vista previa

Para revisar solamente la interfaz:

```bash
python3 demo/orquestador.py --vista-previa
```

También usa el puerto 8090, por lo que no debe iniciarse a la vez que la consola real. La vista previa muestra un aviso y bloquea las acciones; no genera por sí sola tráfico ni resultados reales.

### 6.7 Detener ordenadamente

1. Si hay un escenario activo, usa Cancelar y espera el estado final y la limpieza.
2. Si está levantada la red en reposo, usa Apagar red y espera a que se detenga.
3. Si quieres apagar también Ryu, usa Detener controlador cuando no haya trabajo pesado activo.
4. En la terminal del orquestador, pulsa Ctrl+C para cerrar el servidor.

Para detener el servicio de Compose de este proyecto, después de detener la red y desde su carpeta:

```bash
sudo docker compose down
```

No es necesario desinstalar las herramientas para detener la demo. Cerrar solo el navegador no apaga automáticamente el laboratorio.

### 6.8 Si clonas el proyecto en otra carpeta o máquina

```bash
git clone https://github.com/mort1zr/qos-adaptativa.git
cd qos-adaptativa
git switch demo-consola
```

Después instala los requisitos en el Ubuntu de destino y usa los pasos manuales de arranque. Los scripts de `outputs` **no forman parte del repositorio** y el de arranque contiene la ruta absoluta de esta copia; no funcionará sin adaptar esa ruta si lo llevas a otro lugar.

El acceso directo también contiene una ruta absoluta. Regénéralo desde la nueva copia:

```bash
python3 demo/instalar_acceso.py
```

Los CSV de demo y las capturas tampoco llegan al clonar GitHub: se entregaron aparte y los resultados de demo están ignorados por Git.

## 7. Cómo practicar con la página

### 7.1 Primer ensayo: reconocer la red

1. Abre `http://127.0.0.1:8090`.
2. Comprueba que no aparezca el aviso de Vista previa.
3. Revisa Controlador: debe indicar En línea. Si está apagado y el modo es Docker, pulsa Iniciar controlador y espera.
4. Si la red está apagada, pulsa Levantar red.
5. Espera a que el contador llegue a 44/44; el armado puede tardar.
6. Abre Topología y selecciona Sala 1.
7. Ubica sus seis segmentos y los 74 equipos.

El clic sobre una sede abre su detalle; no cambia el cableado.

### 7.2 Segundo ensayo: evidencias

En Evidencias, selecciona Sala 1 y prueba los cuatro botones:

- **Switches y controlador:** bridges de acceso y conexión a Ryu.
- **Reglas OpenFlow:** busca `set_queue:N`, cookie `0x20` y, cuando haya flujos, `0x16`.
- **Colas HTB:** observa clases, bytes enviados y descartes en subida y bajada.
- **Configuración QoS:** verifica `linux-htb` y las colas asociadas.

La evidencia consulta el sistema real. La presencia de reglas anticipadas depende del clasificador activo: con `ninguno` no debes esperar las mismas reglas de prioridad que con `destino`.

En la validación se seleccionó `destino` y se observaron 346 reglas anticipadas para Sala 1. El número es una observación de esta configuración, no una constante universal.

### 7.3 Tercer ensayo: comparación principal ya comprobada

En Demo selecciona exactamente:

```text
Escenario:      respaldo_en_atencion
Sala:           1
Estrategia:     sin_qos
Comparar con:   prioridad
Rápido:         desmarcado
Acción:         Comparar
```

Qué ocurrirá:

1. Se apagará la red en reposo si estaba levantada.
2. El escenario construirá su propia red.
3. Ejecutará normal → respaldo → normal_otra_vez para `sin_qos`.
4. Ejecutará las mismas fases para `prioridad`.
5. Llenará dos tablas y guardará las filas.
6. Limpiará su red al terminar.

Cada estrategia tiene fases de 30, 60 y 30 segundos, más armado y mediciones. Comparar ejecuta ambas, así que no debes interpretar la duración de una sola estrategia como duración total. Reserva varios minutos.

Mientras corre, puedes mirar Topología, Tráfico y Evidencias. Los controles manuales de clasificador se bloquean porque el escenario define la estrategia.

Al terminar, que la red figure apagada y el contador vuelva a cero **no significa que el escenario falló**: el proceso limpia su propia red. Lee el estado terminado/fallido y conserva las tablas. Para volver a explorar la red sin tráfico, pulsa Levantar red.

### 7.4 Qué observar

En la fila `respaldo`, compara voz, MOS, pagos y web. En nuestra corrida la versión sin QoS incumplió los objetivos y la versión con prioridad los cumplió.

Los resultados son mediciones de cada nueva corrida: pueden variar por carga de la VM, planificación del sistema y comportamiento TCP. No deben coincidir hasta el último decimal para que la prueba sea útil.

### 7.5 Cuarto ensayo: enlace degradado

Selecciona:

```text
Escenario:      enlace_degradado
Sala:           1
Estrategia:     prioridad
Acción:         Correr escenario
```

Tiene normal → degradado → recuperado. En la degradación el operador entrega el 30 % de la capacidad y añade 0,5 % de pérdida.

En esta sesión se probó en modo rápido. Normal y degradado fueron válidos, pero recuperación tuvo CPU alta. Para la presentación, la comparación principal tiene evidencia más sólida porque sus seis fases fueron válidas.

Este escenario sirve para explicar un límite: priorizar en la sede no garantiza resolver una degradación del operador. Eso abre la investigación de decisiones adaptativas futuras; no demuestra que una IA ya resuelva el problema.

### 7.6 Lectura de la pantalla

- **✓:** la fila evaluada cumple el criterio correspondiente.
- **✗:** queda fuera del objetivo.
- **—:** todavía no hay medición, falta un valor o la sonda no está activa.
- **Fase no válida por CPU:** no debe utilizarse como evidencia concluyente aunque algunos números parezcan buenos.
- La demanda por segmentos se muestra como media de una ventana de dos minutos, sumando sentidos.
- El panel antiguo usa otras ventanas, indicadas en sus títulos; no todo número es una lectura instantánea.
- El mapa usa muestras recientes para los enlaces y, durante una degradación, la capacidad disponible para su porcentaje.
- El tiempo mostrado como simulado pertenece al escenario, no al reloj real de la presentación.

## 8. Cómo repetir las pruebas y conservar resultados

### 8.1 Consultas sin levantar una red nueva

Desde la raíz del repositorio:

```bash
curl -fsS http://127.0.0.1:8090/demo/estado
curl -fsS http://127.0.0.1:8080/qos/estado
python3 controlador/api.py estado
```

Estas consultas leen el estado. La API debe estar encendida para responder.

### 8.2 Ver escenarios y planes sin sudo

```bash
python3 escenarios/escenario.py --listar
python3 escenarios/escenario.py --nombre respaldo_en_atencion --plan
python3 escenarios/escenario.py --nombre enlace_degradado --plan --escala 0.5
```

`--plan` enseña las fases e intensidades; no prueba la conectividad ni genera tráfico.

### 8.3 Pruebas de código

```bash
python3 -m unittest discover -p 'test_*.py'
```

No uses sudo para la batería completa como primer recurso. Algunas pruebas usan puertos locales y una base OVS temporal propia. En la validación final, sin ejecutar toda la batería como root, se obtuvieron 187 casos: 186 correctos y uno omitido por requerir sudo.

Para ejecutar solamente las pruebas nuevas más relevantes:

```bash
python3 -m unittest escenarios.test_progreso controlador.test_topologia demo.test_orquestador demo.test_red
```

Para generar un informe compatible con herramientas de CI:

```bash
python3 ci/pruebas_junit.py --salida resultados-pruebas-demo.xml
```

Un resultado exitoso de estas pruebas no sustituye el ensayo con Mininet y tráfico real.

### 8.4 Revisión con pyflakes en un entorno de desarrollo

Si necesitas preparar un entorno separado para el lint:

```bash
mkdir -p ../work
python3 -m venv ../work/venv-desarrollo
../work/venv-desarrollo/bin/python -m pip install PyYAML==6.0.3 pyflakes==3.2.0
../work/venv-desarrollo/bin/python -m pyflakes controlador escenarios trafico experimentos politicas topologia ci demo
```

Este entorno no sustituye el Python 3.9 del controlador. Se ubica en la carpeta de trabajo exterior al repositorio para conservar separados los archivos de desarrollo y el código versionado.

En la sesión se descargó pyflakes a una carpeta de trabajo externa al repositorio y no se instaló en el Python del sistema.

### 8.5 Repetir la comparación por terminal

Usa esto como alternativa para comprender el código o diagnosticar. **Primero detén cualquier red o escenario desde la consola y espera que termine.** El controlador debe seguir en línea. No arranques una red manual simultánea con otra gestionada por la consola.

```bash
sudo python3 escenarios/escenario.py \
  --nombre respaldo_en_atencion \
  --estrategia sin_qos,prioridad \
  --sala 1 \
  --semilla 7 \
  --ruido 0 \
  --escala 1 \
  --salida experimentos/resultados/demo_practica_01.csv \
  --progreso datos/progreso.json
```

Esto guarda `demo_practica_01.csv` y `demo_practica_01_contexto.csv`. Usa nombres distintos si quieres separar repeticiones. Si repites la misma ruta, se agregan filas; no se reemplaza automáticamente la corrida anterior.

Una corrida manual no crea un trabajo en memoria del orquestador. Para la presentación y para controlar los botones, es preferible ejecutarla desde la página. No uses los botones de arranque/limpieza sobre una corrida manual en curso.

### 8.6 Red en reposo por terminal

Alternativa de diagnóstico, también sin otra red activa:

```bash
sudo python3 topologia/empresa_xyz.py \
  --sin-cli --esperar --estrategia colas --datapath kernel
```

Espera a `*** Red lista`. Ctrl+C detiene esa red y recorre su limpieza. Para practicar la presentación usa preferentemente Levantar red desde la consola.

### 8.7 Consultar evidencias directamente

Con la red levantada:

```bash
sudo ovs-vsctl show
sudo ovs-ofctl -O OpenFlow13 dump-flows acc1
sudo tc -s class show dev acc1-eth2
sudo tc -s class show dev acc1-eth1
sudo ovs-vsctl list QoS
```

Son consultas de lectura. `acc1-eth2` corresponde a bajada y `acc1-eth1` a subida en esta topología. Para la exposición, la pestaña Evidencias presenta estas consultas sin tener que escribirlas.

### 8.8 Dónde quedan los resultados

| Archivo | Contenido |
|---|---|
| `experimentos/resultados/demo.csv` | Filas de las fases ejecutadas desde la consola. |
| `experimentos/resultados/demo_contexto.csv` | Relación entre fases y tiempos reales/simulados. |
| `datos/progreso.json` | Progreso y métricas de la corrida actual o más reciente. |
| `datos/reloj.json` | Referencia del reloj simulado. |
| `datos/telemetria.db` | Histórico de telemetría SQLite. |
| `datos/demo.log` | Registro del orquestador y subprocesos; con rotación limitada. |
| `datos/arranque-demo.log` | Registro del script local de arranque usado en esta sesión. |
| `datos/orquestador.log` | Registro utilizado por el otro script de arranque del repo. |

El JSON de progreso se actualiza para la nueva corrida. Si quieres conservar una corrida específica, copia su JSON antes de ejecutar otra. El CSV acumula filas.

Para ver las filas con la biblioteca estándar:

```bash
python3 - <<'PY'
import csv
with open('experimentos/resultados/demo.csv', newline='') as archivo:
    for fila in csv.DictReader(archivo):
        print(fila.get('escenario'), fila.get('estrategia'), fila.get('fase'),
              fila.get('voz_lat95_ms'), fila.get('pagos_p95_ms'),
              fila.get('web_p95_ms'), fila.get('valida'))
PY
```

Los CSV de demo están ignorados por Git. Que `git status` esté limpio no demuestra que no se hayan ejecutado nuevas corridas; por eso se conservaron evidencias aparte y se verificaron los históricos por hashes.

## 9. Resultados reales y límites de lo comprobado

### 9.1 Comparación principal: configuración

```text
Escenario: respaldo_en_atencion
Sala: 1
Estrategias, en orden: sin_qos, prioridad
Semilla: 7
Ruido: 0
Escala: 1
Fases por estrategia: normal 30 s, respaldo 60 s, normal_otra_vez 30 s
```

### 9.2 Resultados de las seis fases

| Estrategia | Fase | Voz p95 ms | MOS | Pagos p95 ms | Web p95 ms | CPU % | Válida |
|---|---|---:|---:|---:|---:|---:|---|
| sin_qos | normal | 97,19 | 4,35 | 34,8 | 601,6 | 30,3 | Sí |
| sin_qos | respaldo | 394,24 | 3,07 | 850,3 | 5778,8 | 61,2 | Sí |
| sin_qos | normal_otra_vez | 95,65 | 4,35 | 81,8 | 511,0 | 24,6 | Sí |
| prioridad | normal | 11,98 | 4,40 | 33,7 | 296,6 | 30,0 | Sí |
| prioridad | respaldo | 13,97 | 4,40 | 29,2 | 1051,8 | 47,6 | Sí |
| prioridad | normal_otra_vez | 12,49 | 4,40 | 31,6 | 470,1 | 32,0 | Sí |

Objetivos utilizados: voz p95 hasta 150 ms y MOS mínimo 4; pagos hasta 500 ms; web hasta 3000 ms. La evaluación de voz del código también considera jitter y pérdida, por lo que mirar solo la latencia no sustituye la columna de cumplimiento.

En la fase respaldo, el goodput del respaldo fue 18,43 Mbps sin QoS y 20,89 Mbps con prioridad. No debe afirmarse que en esta corrida el respaldo se volvió más lento: los valores observados muestran lo contrario. La QoS puede cambiar varios efectos de colas y transporte; no hay que prometer el mismo resultado en todas las cargas.

### 9.3 Enlace degradado: configuración y resultado

```text
Escenario: enlace_degradado
Estrategia: prioridad
Sala: 1
Escala: 0,5
Fases: normal 15 s, degradado 30 s, recuperado 15 s
```

| Fase | Voz p95 ms | MOS | Pagos p95 ms | Web p95 ms | CPU % | Válida |
|---|---:|---:|---:|---:|---:|---|
| normal | 12,17 | 4,40 | 31,6 | 397,6 | 39,6 | Sí |
| degradado | 307,61 | 3,62 | 1817,1 | 5150,8 | 37,9 | Sí |
| recuperado | 37,79 | 4,38 | 173,0 | 465,2 | 92,7 | **No** |

La fase degradada redujo la capacidad al 30 % y añadió 0,5 % de pérdida. La recuperación **no es evidencia concluyente** porque el criterio del proyecto invalida fases con CPU desde 90 %. Sus números se conservan, pero no se presentan como éxito validado.

### 9.4 Qué conclusión es defendible

En la corrida comparativa observada, la estrategia prioridad mantuvo voz, pagos y web dentro de los objetivos durante el respaldo, mientras la referencia sin QoS quedó fuera de ellos. Eso acredita una demostración funcional del laboratorio.

No acredita por sí solo que el sistema funcione igual en cualquier empresa, carga, hardware o red real de producción. Tampoco demuestra causalidad individual de cada mecanismo: `sin_qos` y `prioridad` difieren en clasificación y organización de colas. Para aislar el efecto de clasificar respecto de tener filas cortas, `fila_corta` es una referencia útil que todavía debes ensayar con ese propósito.

No se hizo una campaña estadística repetida en esta sesión. La misma semilla reproduce el plan de carga; no garantiza tiempos idénticos del kernel y del transporte.

## 10. Qué mostrar y cómo explicarlo al profesor

### 10.1 Mensaje principal

Puedes explicarlo con tus propias palabras a partir de este texto:

> Nuestro avance consiste en una red empresarial virtual con cinco sedes y un controlador SDN. Generamos tráfico para observar qué ocurre cuando un respaldo compite con voz, pagos y navegación. Comparamos una referencia sin QoS con una estrategia que clasifica por destino y aplica colas por clase. En la corrida comprobada, la voz pasó de aproximadamente 394 a 14 milisegundos durante el respaldo, y también mejoraron pagos y web. La consola permite observar los switches, reglas, colas y resultados reales. La IA es la siguiente etapa, una vez consolidada esta base.

No lo memorices sin entender el recorrido. Debes poder conectar cada frase con una pantalla o un archivo.

### 10.2 Guion de 8 a 10 minutos

| Momento aproximado | Qué haces | Qué explicas |
|---|---|---|
| 0:00–0:40 | Presentas el problema. | Aplicaciones con necesidades distintas compiten por un enlace limitado. |
| 0:40–1:20 | Muestras controlador y 44/44. | Hay una red virtual real conectada a Ryu, no solo una maqueta dibujada. |
| 1:20–2:00 | Topología, clic en Sala 1. | Cinco sedes, seis segmentos en Sala 1 y clasificación de demanda. |
| 2:00–2:40 | Evidencias de reglas y colas. | OpenFlow selecciona colas y Linux aplica los parámetros HTB. |
| 2:40 en adelante | Ejecutas la comparación principal. | Dos estrategias, mismo escenario y semilla; varias fases por estrategia. |
| Durante la espera | Muestras Tráfico y explicas un recorrido de código. | El controlador decide; el switch aplica; las sondas miden. |
| Al terminar | Comparas las dos filas de respaldo. | Diferencia medida frente a los objetivos y validez de las fases. |
| Cierre | Presentas alcance y próximos pasos. | Campañas repetidas, robustez e IA en desarrollo; CI/CD preparado, no acreditado en Azure aquí. |

El tiempo depende de la VM. Ensaya el recorrido antes de exponer y lleva las capturas como respaldo. No presentes una captura previa como si fuera una ejecución en vivo.

### 10.3 Las cuatro evidencias más importantes

1. **44/44:** conexión entre switches y controlador.
2. **`set_queue`:** regla que asigna un flujo a una cola.
3. **HTB con contadores:** existe configuración y actividad en el plano de datos.
4. **Tabla comparativa:** la medición de las aplicaciones cambia bajo la carga ensayada.

La página por sí sola no prueba la QoS; la combinación de red conectada, reglas, contadores y mediciones es lo que respalda la demostración.

### 10.4 Si pregunta por IA o Azure

**IA:** “Está prevista para los siguientes sprints. En este avance validamos la base de red, telemetría y estrategias de referencia. La estrategia actual usa reglas y destinos conocidos.”

El perfil llamado `ia_generativa` representa tráfico de usuarios hacia un servicio simulado; no significa que exista un modelo entrenado controlando la red.

**Azure:** “Tenemos la definición de CI/CD y scripts para pruebas, imagen y despliegue al laboratorio. En esta sesión se verificó la ejecución local. No estamos presentando como comprobada una ejecución del pipeline en Azure DevOps.”

Azure DevOps y una VM alojada en Azure son cosas distintas. Usar Azure DevOps no obliga a mover Mininet a la nube.

### 10.5 Si pregunta por código

Recorrido que conviene dominar:

```text
Botón en demo/consola/index.html
    -> acción validada en demo/orquestador.py
    -> escenario.py configura estrategia y ejecuta fases
    -> clasificadores.py determina clase
    -> qos_app.py instala regla set_queue
    -> colas.py configura el tratamiento en OVS/Linux
    -> sondas y telemetria.py producen mediciones
    -> progreso.py y CSV guardan datos
    -> la consola presenta esos datos
```

`set_queue` selecciona una cola; no crea por sí solo toda la configuración HTB. Para completar el mecanismo se necesitan la configuración de colas y el reenvío de paquetes.

## 11. Cómo variar políticas, escenarios y topología

### 11.1 Qué puedes cambiar desde la página

Sin editar archivos puedes:

- Elegir uno de los diez escenarios existentes.
- Cambiar entre las salas 1 a 4.
- Elegir una estrategia.
- Comparar dos estrategias diferentes.
- Usar modo rápido o duración completa.
- Seleccionar sedes y evidencias.
- Cambiar de clasificador en Tráfico cuando el escenario no lo controle.

Para obtener ejemplos variados antes de la presentación, esta es la vía más sencilla. No se modificaron ahora tus YAML para crear ejemplos nuevos.

### 11.2 Estrategia y clasificador no significan lo mismo

| Estrategia | Colas y tratamiento | Clasificador de Ryu |
|---|---|---|
| `sin_qos` | Una cola de referencia con FIFO larga. | `ninguno`. |
| `fila_corta` | Seis colas con filas cortas; tráfico sin selección explícita cae en la predeterminada. | `ninguno`. |
| `prioridad` | Colas por clase con filas cortas y selección de cola. | `destino`. |
| `estatica` | Lo anterior más techos que cambian según horario simulado. | `destino`. |

El clasificador `politica` también existe para clasificación con la información de políticas e inventario, pero la estrategia `prioridad` de los escenarios usa `destino`.

Cambiar un botón de clasificador en Tráfico no configura por sí solo todas las colas de una estrategia. Para una comparación reproducible utiliza las estrategias del escenario.

### 11.3 Ejemplos existentes que puedes explorar

| Ejemplo | Selección | Qué permite estudiar |
|---|---|---|
| Comparación ya comprobada | respaldo_en_atencion; sin_qos vs prioridad; Sala 1; duración completa. | Efecto conjunto de clasificación y colas bajo respaldo. |
| Control adicional | respaldo_en_atencion; fila_corta vs prioridad. | Qué añade la selección de clase frente a tener filas cortas. |
| Fallo del operador | enlace_degradado; prioridad. | Límite de las políticas frente a menos capacidad y pérdida. |
| Demanda de clientes | noche_alta; sin_qos vs prioridad. | Carga alta de WiFi y otros servicios. |
| Horario | respaldo_en_atencion; prioridad vs estatica. | Techo del tráfico masivo durante atención. |
| Otro enlace | Repetir en Sala 4. | Capacidad de 10 Mbps y mayor retardo configurado. |
| Apertura | apertura; prioridad vs estatica. | Cambios durante la apertura y horario simulado. |

Solo las corridas detalladas en la sección 9 se ejecutaron y validaron aquí. Los demás son ejemplos para ensayar, sin resultados prometidos.

### 11.4 ¿Puedo mover los equipos con el mouse?

**No actualmente.** El mapa es una visualización determinista con clic para abrir sedes. No es un editor de red: no tiene arrastrar, añadir equipos, cambiar cables o reubicar enlaces en vivo.

Hay que distinguir tres acciones:

- **Mover el dibujo:** requeriría implementar edición de la visualización.
- **Cambiar la red simulada:** se hace en YAML/código y reconstruyendo la red.
- **Mover el proyecto a otra computadora:** se clona la rama, se instalan requisitos y se adaptan rutas locales.

### 11.5 Flujo recomendado para un cambio de ejemplo

1. Termina la corrida actual y guarda sus resultados.
2. Apaga la red y el controlador si vas a cambiar configuración que cargan al iniciar.
3. Cierra el orquestador con Ctrl+C cuando necesite recargar su configuración/lista.
4. En una rama local de pruebas, conserva la configuración original y cambia una sola variable.
5. Valida YAML, políticas y plan antes de ejecutar tráfico.
6. Reinicia los componentes que lean esa configuración.
7. Repite el experimento con un nombre de CSV nuevo.
8. Documenta qué cambió y qué se mantuvo.

Ejemplo de rama local, si decides hacer ese trabajo:

```bash
git switch -c ejemplos-demo
```

Crear otra rama no cambia los resultados anteriores ni ejecuta la red. No se creó esa rama durante esta sesión.

### 11.6 Cambiar un escenario existente

Archivo: `escenarios/escenarios.yaml`.

Puedes variar duración de fase, intensidad de un perfil o degradación del enlace. Por ejemplo, para explorar más demanda de WiFi en una fase podrías cambiar `wifi_clientes: 0.5` por `wifi_clientes: 2`.

Eso cambia la carga ofrecida; **no garantiza exactamente cuatro veces el caudal medido**, porque algunos perfiles cambian cantidad de clientes, otros frecuencia y los enlaces limitan el resultado.

Después valida:

```bash
python3 escenarios/escenario.py --listar
python3 escenarios/escenario.py --nombre respaldo_en_atencion --plan
python3 -m unittest escenarios.test_escenarios
```

Las pruebas existentes comprueban aspectos del catálogo actual. Si añades un escenario, alguna prueba que espera exactamente diez nombres necesitará actualizarse de manera justificada, manteniendo cobertura.

El orquestador carga el catálogo al arrancar: **reinícialo para ver escenarios nuevos o sus descripciones actualizadas en la consola**.

### 11.7 Ejemplo de escenario nuevo, todavía no implementado ni ensayado

Puedes añadir el siguiente bloque dentro del mapa `escenarios:` del YAML existente. Mantén los espacios y no reemplaces el resto del documento:

```yaml
  demo_wifi:
    descripcion: "Comparación de demanda normal y alta de WiFi de clientes."
    inicio: {dia: martes, hora: "16:00"}
    fases:
      - nombre: normal
        duracion_s: 30
        sala:
          maquinas_reporte: 1
          pagos_pos: 1
          camara_remota: 1
          wifi_clientes: 0.5
      - nombre: wifi_alto
        duracion_s: 60
        sala:
          maquinas_reporte: 1
          pagos_pos: 1
          camara_remota: 1
          wifi_clientes: 3
      - nombre: recuperado
        duracion_s: 30
        sala:
          maquinas_reporte: 1
          pagos_pos: 1
          camara_remota: 1
          wifi_clientes: 0.5
```

Se usan perfiles que existen. Después de editar:

```bash
python3 escenarios/escenario.py --nombre demo_wifi --plan
```

Actualiza la prueba del catálogo si corresponde, reinicia el orquestador y entonces ensaya la nueva opción. Los criterios de validez y medición siguen siendo los mismos; no deben ajustarse para forzar colores verdes.

### 11.8 Cambiar el enlace de una sala

Archivo: `topologia/empresa_xyz.yaml`.

Por ejemplo, dentro de Sala 1:

```yaml
enlace: {mbps: 20, retardo_ms: 5}
```

Eso sustituiría los 30 Mbps actuales por 20 Mbps en una nueva construcción. Debes apagar y volver a levantar la red; mover un selector del mapa no cambia el enlace existente.

Puedes modificar cantidades de equipos existentes, pero evita ampliar mucho la red en la VM de 4 GB. El conteo de equipos y switches puede dejar de ser 276/44, y tus explicaciones y pruebas deberán reflejarlo.

Añadir una Sala 5 requiere revisar más que el YAML: los argumentos, listas permitidas y controles actuales se limitan a salas 1–4.

### 11.9 Cambiar una política

Archivos según el objetivo:

| Archivo | Cambio |
|---|---|
| `politicas/politicas.yaml` | Clases, reglas, garantías, techos y prioridades. |
| `politicas/destinos.yaml` | Identificación de servicios por destinos conocidos. |
| `politicas/horario.yaml` | Techos por franjas para la estrategia estatica. |
| `trafico/perfiles.yaml` | Cómo se generan las cargas, no la política que las atiende. |

Ejemplo exploratorio: cambiar el techo de `restringido` del 20 % al 10 %, manteniendo su garantía del 2 %, para estudiar el trato al WiFi de clientes.

Valida antes:

```bash
python3 politicas/cargador.py
python3 -m unittest politicas.test_cargador controlador.test_clasificadores
```

Reglas que debes conservar:

- La suma de garantías no supera 100 %.
- El techo de una clase no queda por debajo de su garantía.
- Los identificadores de colas son únicos.
- La cola 0 mantiene la relación requerida con la clase de tráfico desconocido.
- No cambies identificadores y prioridades sin comprender su efecto.
- No confundas la prioridad de una clase con el número de su cola: no son la misma cosa.

Ryu carga sus políticas en memoria al iniciar. No basta con guardar un YAML para asegurar que el controlador activo ya lo esté usando.

En **modo Docker Compose**, `politicas/` está montado desde el host. Después de detener cualquier red/escenario, puedes reiniciar el controlador para releer las políticas:

```bash
sudo docker compose restart controlador
```

Después vuelve a levantar la red o ejecutar el escenario para que las colas también se configuren con el mismo conjunto de políticas.

En modo **lab del pipeline**, las políticas van dentro de la imagen del despliegue: hace falta reconstruir/desplegar esa imagen. No supongas que un cambio en el host actualiza ambos modos igual.

### 11.10 Cambios de código del controlador y de la consola

- Si cambias `controlador/*.py` que corre dentro de Docker, reconstruye la imagen y recrea el contenedor, con la red detenida.
- Si cambias `demo/orquestador.py`, reinicia su proceso desde la terminal.
- Si cambias `demo/consola/index.html`, recarga el navegador; el orquestador sirve ese archivo desde el host.
- Si cambias los YAML que el orquestador conserva en memoria, reinícialo.

Antes de la exposición, conserva una versión ya ensayada y evita introducir varias modificaciones simultáneas. Para mostrar variedad mañana, las selecciones existentes de la página ofrecen ejemplos sin tener que editar el proyecto.

## 12. Solución de problemas

| Síntoma | Qué revisar |
|---|---|
| La página no abre. | ¿Sigue abierta la terminal del orquestador? ¿Estás en el navegador de Ubuntu? ¿Usas 8090? |
| Aparece Vista previa y botones deshabilitados. | Se inició con `--vista-previa`; usa el arranque real cuando no haya otro servidor en 8090. |
| Controlador apagado. | Revisa Docker, el modo `docker` y sus registros. |
| Mensaje de que no existe despliegue del pipeline. | Se está usando `lab`; para esta instalación se probó `--controlador docker`. |
| Puerto ocupado. | Ya hay otro orquestador o controlador. Identifica y detén el proceso correspondiente de forma ordenada; no lances duplicados. |
| Red iniciando o contador parcial. | Espera el armado y revisa el registro. No pulses repetidamente Levantar red. |
| No hay mapa. | La red debe generar inventario al levantarse al menos una vez. |
| No hay decisiones nuevas sin tráfico. | El clasificador registra flujos; genera un escenario y espera sus sondeos. |
| El cambio de clasificador está bloqueado. | Es correcto mientras el escenario controla la estrategia. |
| Al terminar el escenario hay cero switches conectados. | El escenario limpia su red. Levanta la red en reposo si quieres seguir explorándola. |
| Una fase tiene CPU alta. | No la uses como evidencia concluyente. Cierra aplicaciones innecesarias y repite; no cambies el umbral para aprobarla. |
| Números de demanda y enlace no coinciden exactamente. | Revisa sentidos, ventanas temporales y si miras demanda ofrecida o tráfico reenviado. |
| Los resultados nuevos difieren de la captura. | La VM y TCP introducen variación. Compara objetivos, validez y configuración, no igualdad decimal. |
| Cambiaste un YAML y no se refleja. | Reinicia el componente que lo carga y reconstruye la red cuando corresponda. |
| Permission denied en Docker/OVS. | En esta instalación se usan los comandos administrativos con sudo desde tu terminal. |

Comandos de diagnóstico desde la carpeta del proyecto:

```bash
curl -fsS http://127.0.0.1:8090/demo/estado
curl -fsS http://127.0.0.1:8080/qos/estado
sudo docker compose ps
sudo docker compose logs --tail=80 controlador
tail -n 80 datos/arranque-demo.log
tail -n 80 datos/demo.log
free -h
```

Si una red gestionada quedó colgada, usa Limpiar todo desde la consola y revisa el mensaje. No utilices `sudo mn -c` indiscriminadamente mientras hay una corrida en curso: limpia recursos globales de Mininet y puede afectar controladores del host. En modo Docker, Ryu está separado de ese proceso del host, pero la red y las mediciones sí pueden perderse.

## 13. GitHub: commits, rama y confirmación sobre main

### 13.1 Respuesta directa

**Se hicieron y publicaron seis commits de implementación y validación en `demo-consola`. Este documento se incorpora después como séptimo commit de documentación en esa misma rama.**

**Sí: se utilizó `main` como punto de partida para clonar la base.**

**No: no se movió la referencia de `main`, no se hizo merge y no se publicaron cambios sobre ella.**

Trabajar en una rama utiliza archivos en la misma carpeta de trabajo de Git, pero los commits se asignan a la rama activa. Modificar esos archivos mientras está activa `demo-consola` no modifica automáticamente la referencia de `main`.

### 13.2 Commits de implementación y validación publicados

| Orden | Commit | Propósito |
|---|---|---|
| 1 | `88731a8` | Integrar la base Sprint 3: panel, CI/CD, Docker y especificación. |
| 2 | `6f90133` | Progreso de escenarios y resultados separados de demo. |
| 3 | `4813fc4` | API de topología y red en reposo con limpieza al detener. |
| 4 | `6b6bddb` | Orquestador y consola de cuatro vistas. |
| 5 | `3febeb2` | Elegir modo Docker al arrancar sin editar la configuración guardada. |
| 6 | `0f7968c` | Documentar la validación real y ajustar indicadores de la consola. |

Enlaces:

- [Rama demo-consola](https://github.com/mort1zr/qos-adaptativa/tree/demo-consola).
- [Historial de demo-consola](https://github.com/mort1zr/qos-adaptativa/commits/demo-consola/).
- [Comparación entre main y demo-consola](https://github.com/mort1zr/qos-adaptativa/compare/main...demo-consola).
- [Documento de validación publicado](https://github.com/mort1zr/qos-adaptativa/blob/demo-consola/docs/VALIDACION_LOCAL.md).

A esos seis commits se añade el commit que incorpora `docs/CONTEXTO_COMPLETO_Y_GUIA_DEMO_QOS.md`. Su propósito es registrar esta documentación, sin alterar el comportamiento del laboratorio.

No se creó un pull request ni se realizó una fusión.

### 13.3 Referencias verificadas antes del commit de este documento

```text
main:
86782458ae549a68a46e92102a7c8959065a6ddc

demo-consola:
0f7968c7da2d5ebd31c5029305fe8f1c5c0596e5
```

Estas referencias son la instantánea anterior al commit de este documento: se comprobaron tanto localmente como en GitHub. En ese momento el árbol de trabajo estaba limpio y `demo-consola` estaba sincronizada con `origin/demo-consola`. El commit documental posterior cambia la punta de `demo-consola`; no cambia la base `main` ni el código validado en `0f7968c`.

Antes de añadir este documento, la rama modificaba 36 archivos respecto de la base. Este Markdown añade un archivo más. Son cambios de `demo-consola`, no cambios fusionados en `main`.

### 13.4 Cómo comprobarlo tú

```bash
git status --short --branch
git branch -vv
git log --oneline main..demo-consola
git diff --stat main...demo-consola
git ls-remote --heads origin refs/heads/main refs/heads/demo-consola
```

El último comando consulta GitHub y necesita conexión a Internet. Los nombres y hashes pueden cambiar si tú o tu compañero publican nuevos commits después de este documento.

Para obtener la rama en la copia de tu compañero:

```bash
git fetch origin
git switch demo-consola
```

Si tiene cambios locales sin guardar, debe revisarlos antes de cambiar de rama. No es necesario fusionar con `main` para revisar o ejecutar la rama de la demo.

### 13.5 Qué significa commit, push y merge

- **Commit:** punto de guardado del historial local.
- **Push:** envío de esos commits a una rama remota.
- **Pull request:** propuesta de revisión para integrar una rama.
- **Merge:** integración efectiva de una rama en otra.

Aquí se hicieron commits y push en `demo-consola`. No se hizo merge en `main`.

Git se configuró con el nombre de la cuenta y el correo de privacidad ofrecido por GitHub, únicamente para este repositorio. La autenticación de la terminal se completó con GitHub CLI y autorización del usuario en el navegador. Las credenciales no se añadieron al repositorio ni a los commits.

Este Markdown se conserva en `outputs` como entregable local y se registra también en `docs/CONTEXTO_COMPLETO_Y_GUIA_DEMO_QOS.md` mediante un séptimo commit documental solicitado por el usuario. Documenta el trabajo realizado y la asistencia utilizada; no representa una implementación adicional de IA o nuevas mediciones.

## 14. Glosario y preguntas probables

| Término | Explicación para la sustentación |
|---|---|
| QoS | Tratamiento y distribución de recursos de red según clases y políticas. |
| SDN | Separación del control programable y el reenvío de paquetes. |
| Plano de control | Decide las reglas; aquí lo representa Ryu. |
| Plano de datos | Aplica las reglas y transporta los paquetes; aquí OVS/Linux. |
| Flujo | Conjunto de paquetes que coincide con determinados campos de una regla. |
| OpenFlow | Protocolo de reglas y estadísticas entre controlador y switches. |
| HTB | Mecanismo jerárquico de distribución y límites de ancho de banda. |
| Garantía | Parte configurada como tasa mínima de una clase, sujeta al contexto del enlace. |
| Techo | Máximo configurado al que puede llegar esa clase al disponer de recursos. |
| FIFO larga | Cola que puede acumular muchos paquetes y aumentar la demora bajo carga. |
| Bufferbloat | Aumento de latencia asociado a colas excesivamente largas bajo carga. |
| Latencia | Demora que experimentan los paquetes o una operación, según la medición. |
| p95 | Percentil 95: aproximadamente el 95 % de muestras no supera ese valor. |
| Jitter | Variación del retardo de los paquetes. |
| Pérdida | Porcentaje de paquetes que no llegaron según la medición. |
| MOS | Estimación de calidad de voz calculada por el proyecto; no una encuesta de usuarios. |
| Goodput | Datos útiles recibidos por la aplicación por unidad de tiempo. |
| Mbps | Megabits por segundo; no equivale a megabytes por segundo. |
| Telemetría | Mediciones recolectadas para observar la red y sus decisiones. |
| Namespace | Espacio de red separado del kernel usado para los equipos virtuales. |
| CI | Integración continua: verificar cambios automáticamente. |
| CD | Entrega/despliegue automatizado según el proceso configurado. |

**¿La red es real o una imagen?**

Es una red virtual ejecutándose con interfaces, procesos, OVS y tráfico real de laboratorio. La página dibuja una representación y la controla. No son 276 dispositivos físicos.

**¿Se usa Teams, YouTube o ChatGPT de verdad?**

No en estos experimentos. Hay servidores, direcciones y perfiles que representan esos servicios. El código genera tráfico y transacciones sintéticas para estudiar su comportamiento.

**¿La IA ya clasifica el tráfico?**

No. La estrategia probada usa destinos conocidos y reglas. El perfil de tráfico `ia_generativa` no es el controlador inteligente futuro.

**¿La prioridad fue lo único que cambió?**

La estrategia cambia clasificación y colas/filas respecto de la referencia sin QoS. La comparación muestra su efecto conjunto. Para separar mecanismos conviene ensayar también `fila_corta`.

**¿Por qué mejoró el respaldo también?**

Ese fue el resultado observado en esta corrida. No se debe imponer una historia de que todos los servicios masivos necesariamente empeoran. Las colas y TCP pueden afectar también el caudal útil. No se hizo aquí una campaña para generalizar ese efecto.

**¿Qué significa que una fase sea inválida?**

Que el experimento detectó una condición del host, en este caso CPU desde el umbral, que impide atribuir con confianza el resultado solo a la red. Se conserva el dato pero no se usa como evidencia concluyente.

**¿Por qué hay 276 equipos y 44 switches?**

Son dos conteos distintos: el inventario de equipos y los switches de la topología. Los equipos incluyen ocho servidores de Internet simulado.

**¿Por qué algunos botones están deshabilitados?**

La consola impide acciones incompatibles, como apagar el controlador durante un trabajo pesado o cambiar el clasificador mientras el escenario define su estrategia.

## 15. Archivos de respaldo y contexto para continuar

### 15.1 Entregables locales

Este documento está registrado en el repositorio en `docs/CONTEXTO_COMPLETO_Y_GUIA_DEMO_QOS.md`. Su copia local de entrega está en:

```text
/home/elonmusk/Documents/Codex/2026-10-26/referenced-chatgpt-conversation-this-is-an/outputs/CONTEXTO_COMPLETO_Y_GUIA_DEMO_QOS.md
```

En `outputs/demo-real/` están:

- `GUIA_PARA_LA_PRESENTACION.md`: guion más corto para practicar.
- `INFORME_VALIDACION.md`: resultados y límites de la prueba real.
- `comparacion-respaldo.json`: progreso y métricas de la comparación válida.
- `enlace-degradado.json`: métricas de la corrida que incluyó una fase inválida.
- `demo.csv` y `demo_contexto.csv`: copias de las nueve filas de demo y su contexto.
- `switches-sala1.txt`, `reglas-sala1.txt`, `colas-sala1.txt`, `qos-sala1.txt`: consultas reales guardadas.
- `topologia.json`: estructura real observada desde la API.
- Capturas del mapa, tráfico y resultados.

El archivo `outputs/respaldo-demo-real.zip` agrupa las evidencias de esa carpeta. Los scripts `preparar-ubuntu-demo.sh` e `iniciar-demo-real.sh` están directamente en `outputs` y contienen las acciones explicadas en este documento.

Estos respaldos son fotografías de la validación realizada, no se actualizan automáticamente cada vez que practicas.

### 15.2 Para continuar en otra conversación

Puedes compartir este archivo y resumir el punto de continuación así:

> Proyecto qos-adaptativa, código funcional validado en 0f7968c de demo-consola, con un commit documental posterior que añade esta guía. Main quedó en 8678245 sin merge. En Ubuntu 22.04 ya se instalaron Mininet, OVS y Docker; Ryu corre en Docker y el orquestador usa --controlador docker en localhost:8090. Se verificó la red de 44 switches y 276 equipos. La comparación respaldo_en_atencion, Sala 1, sin_qos contra prioridad, escala 1, tuvo seis fases válidas; la voz durante respaldo pasó de 394,24 a 13,97 ms. La IA y la ejecución de Azure DevOps siguen pendientes. No modificar resultados históricos ni afirmar que la lista de aceptación completa ya pasó. Revisar el estado actual de procesos y archivos antes de seguir.

### 15.3 Preparación final antes de presentar

1. Abre Ubuntu y confirma que no esté pausada la VM.
2. Cierra aplicaciones innecesarias para dejar recursos al laboratorio.
3. Comprueba que la consola sea real y que el controlador responda.
4. Ensaya el recorrido con las mismas opciones de la comparación válida.
5. Verifica los indicadores de validez, no solo los colores de los números.
6. Ten a mano este documento, los CSV y las capturas.
7. Presenta resultados observados y límites con transparencia.
8. Explica el siguiente paso de IA como trabajo futuro sobre una base ya funcional.

**Conclusión que puedes sostener:** se construyó y verificó una base funcional de red SDN y QoS, con mediciones y una consola para demostrarla. En la comparación realizada, la estrategia de prioridad mejoró los servicios evaluados durante el respaldo. La generalización estadística, la robustez completa, la ejecución de CI/CD en Azure y la IA siguen siendo trabajo adicional.
