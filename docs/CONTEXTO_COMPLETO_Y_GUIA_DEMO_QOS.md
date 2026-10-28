# Proyecto QoS adaptativa: contexto completo, operación, pruebas y sustentación

**Documento consolidado y actualizado al 26 de octubre de 2026, zona America/Lima. Incluye la implementación, las primeras pruebas reales, el cierre QA y el ordenamiento del registro publicado en `0003eca`.**

Esta revisión reemplaza la primera versión del documento incorporada en `d3fa14f`. Conserva su historia y actualiza los hechos que cambiaron después. La fecha `2026-10-27` de los directorios QA corresponde a UTC: esas pruebas ocurrieron durante la noche del **26 de octubre en Perú**.

Este documento reúne lo que se encontró, lo que se incorporó y programó, cómo se instaló y ejecutó el laboratorio, los resultados reales obtenidos y cómo practicar y presentar la demo. También explica qué se puede modificar y qué se confirmó en GitHub.

## Lectura rápida: en qué estado quedó el proyecto

- El laboratorio **ya se ejecutó con tráfico real en este Ubuntu**; la página dejó de ser únicamente una vista previa.
- El controlador Ryu funciona dentro de Docker. Mininet, Open vSwitch y las colas de Linux funcionan en el host Ubuntu.
- Se verificaron **44 de 44 switches conectados**, cinco sedes y **276 equipos del inventario**, de los cuales ocho representan servidores de Internet dentro de la simulación.
- Hay **dos comparaciones completas** de `respaldo_en_atencion`, Sala 1, `sin_qos` frente a `prioridad`: seis fases válidas por comparación. No se deben mezclar sus cifras.
- En la primera comparación, durante el respaldo, la voz p95 pasó de **394,24 ms a 13,97 ms**, con MOS 4,40 usando prioridad. En la comparación de cierre QA pasó de **423,01 ms a 16,65 ms**, pero prioridad tuvo **12,04 % de pérdida y MOS 3,2**. Esa segunda corrida no cumplió todos los objetivos de voz.
- La batería de código evolucionó de **187 pruebas** antes del ejecutor QA a **198 en la última ejecución: 197 aprobadas y 1 omitida**, por requerir sudo. El lint de los archivos QA terminó sin avisos.
- El ejecutor `demo/qa_sprint3.py` dejó **11 comprobaciones funcionales aprobadas y 1 caso manual no ejecutado**. Esto es otro conteo, distinto de las 198 pruebas de código.
- Se canceló un escenario con tráfico activo en **21 segundos** y se ejecutó después una comparación completa. El arranque repetido de la red también quedó comprobado.
- Los resultados de demostración se guardan separados de los resultados históricos de la tesis.
- La IA todavía está pendiente. Los resultados actuales corresponden a políticas, clasificación por destino y colas.
- Se incorporó código de CI/CD para Azure DevOps, pero **no se comprobó una ejecución del pipeline en Azure DevOps**.
- Antes de esta actualización documental había **9 commits publicados** sobre la base original, hasta `0003eca`. Esta revisión se registra en un commit documental adicional en **`demo-consola`**; el historial de la sección 13 distingue cada entrega.
- **No se modificó ni se fusionó nada en `main`.**

**Estado consultado el 26/10/2026 a las 23:27, hora de Lima:** consola real en `http://127.0.0.1:8090`, controlador en línea, modo `docker`, red en reposo levantada y **44 switches conectados**. El clasificador estaba en **`ninguno`**, restaurado por QA; esto no significa que la red esté caída. Los escenarios configuran su estrategia al ejecutarse. No había un escenario ni una ejecución QA activos. Son datos de una consulta de lectura, no de una nueva prueba de tráfico.

**Última decisión del usuario:** no ejecutar más QA por ahora. Se conservan el script, sus resultados y los pendientes. Esta actualización solamente documenta y verifica archivos; no vuelve a generar tráfico ni reinicia el laboratorio.

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
16. [Cierre QA: script, códigos únicos, intentos y evidencias](#16-cierre-qa-script-códigos-únicos-intentos-y-evidencias)
17. [GitHub, copia local, VS Code y reproducción en otra VM](#17-github-copia-local-vs-code-y-reproducción-en-otra-vm)
18. [Apagar Ubuntu, conservar el chat y retomar el trabajo](#18-apagar-ubuntu-conservar-el-chat-y-retomar-el-trabajo)
19. [Discrepancias, riesgos y límites que deben quedar claros](#19-discrepancias-riesgos-y-límites-que-deben-quedar-claros)
20. [Punto exacto de continuación y transferencia de contexto](#20-punto-exacto-de-continuación-y-transferencia-de-contexto)

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
- Completar los casos manuales de aceptación todavía no cubiertos, incluido reiniciar Ubuntu y el proceso del orquestador. La cancelación durante tráfico y la ejecución posterior ya se comprobaron.
- Investigar el hallazgo `QOS-01`: pérdida de voz y MOS fuera del objetivo durante el respaldo con prioridad en la última comparación. Su causa no está establecida.
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

La solicitud original referenciaba esos adjuntos bajo `/mnt/data`, pero esa carpeta no estaba disponible en este entorno. Se recuperaron desde la conversación «Evaluación de archivos» y quedaron accesibles mediante archivos temporales:

```text
/tmp/codex-file-preview-lchcvl/sprint3-azure-cicd.zip
/tmp/codex-file-preview-zYowdD/ESPECIFICACION_DEMO.md
```

Estas rutas son transitorias y pueden desaparecer al reiniciar o limpiar temporales. El repositorio integrado y la especificación versionada en `docs/ESPECIFICACION_DEMO.md` son la referencia persistente; la ejecución actual no depende de volver a abrir el ZIP.

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

En la primera etapa se ejecutaron dos experimentos:

1. `enlace_degradado`, prioridad, Sala 1, rápido: tres fases. Dos válidas y una recuperación inválida por CPU alta.
2. `respaldo_en_atencion`, `sin_qos` y `prioridad`, Sala 1, duración completa: seis fases, todas válidas.

Esta primera etapa conservó nueve filas de resultados de demo. No se borró la fila inválida ni se ajustaron criterios para convertirla en válida. El cierre QA posterior añadió seis filas; al preparar esta actualización el archivo local contiene **15 filas**.

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

### 4.11 Primera entrega de documentación y aclaraciones de operación

Se creó la primera versión de este documento y se publicó como `d3fa14f`. Después se explicó cómo volver a arrancar tras apagar la VM, cómo clonar la rama en otro Ubuntu, cómo utilizar la terminal de VS Code y por qué la demo lee archivos locales, no GitHub continuamente. También se distinguió este chat local de Codex de la conversación de ChatGPT originalmente referenciada.

### 4.12 Automatización y ejecución del cierre QA

El usuario pidió que QA se materializara en código ejecutable, sin añadir otro Markdown como supuesto trabajo técnico. Se incorporaron `demo/qa_sprint3.py`, `demo/test_qa_sprint3.py` y `ci/evidencias/qa-sprint3.json`. Hubo dos intentos iniciales fallidos del guion, ajustes de preparación y espera, y una ejecución final funcionalmente aprobada con pendientes. No se ocultaron los intentos fallidos.

La última ejecución tuvo 198 pruebas de código, cancelación en 21 segundos, comparación completa posterior a la cancelación, apagado y nuevo arranque de la red, y comprobación de 21 archivos protegidos. También produjo el hallazgo de pérdida de voz que se conserva como pendiente. La sección 16 detalla los códigos, las horas, las comprobaciones y sus límites.

### 4.13 Publicación de QA y ordenamiento del registro

Se publicó `17bab70` con el ejecutor, sus 11 pruebas nuevas y la evidencia real JSON. Después el usuario pidió conservar los códigos únicos de manera ordenada. `0003eca` ordenó el registro por ID y añadió el orden real de ejecución como referencia. No volvió a ejecutar QA ni cambió mediciones, estados o hallazgos.

El usuario indicó después que no realizaría más pruebas QA. Se respetó esa decisión. La presente revisión actualiza el contexto completo por solicitud expresa del usuario.

## 5. Archivos y módulos que debes conocer

### 5.1 Mapa del proyecto

```text
qos-adaptativa/
  Dockerfile
  docker-compose.yml
  azure-pipelines.yml
  requirements.txt
  ci/                       scripts y documentación de CI/CD
    evidencias/qa-sprint3.json  registro QA publicado, con IDs y hallazgos
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
    qa_sprint3.py           ejecutor QA, básico o con laboratorio real
    test_qa_sprint3.py      11 pruebas del validador y sus protecciones
    demo.yaml               configuración del orquestador
    consola/index.html      página de cuatro pestañas
    iniciar_demo.sh         arranque según configuración guardada
    instalar_acceso.py      genera el acceso directo con ruta real
    QoS-Demo.desktop        acceso directo generado
    README.md               uso y límites de la consola
    test_*.py               pruebas de orquestador, red en espera y ejecutor QA
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

Configuración versionada al cierre:

```yaml
controlador: lab
venv: .venv/bin/ryu-manager
datapath: kernel
resultados_demo: experimentos/resultados/demo.csv
escala_rapida: 0.5
salas: [1, 2, 3, 4]
estrategias: [sin_qos, fila_corta, prioridad, estatica]
```

La opción de arranque sobreescribe el modo de controlador para ese proceso. No reescribe este YAML ni cambia por sí sola políticas o escenarios. El modo rápido modifica la escala de duración; las comparaciones completas documentadas usaron escala 1.

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

En la fila `respaldo`, compara voz, MOS, pagos, web y pérdida. En la primera comparación `sin_qos` incumplió los objetivos y `prioridad` los cumplió para los servicios evaluados. En la comparación QA posterior, prioridad mejoró latencia pero no cumplió pérdida/MOS de voz. Revisa siempre la corrida concreta que está en pantalla; la sección 9 conserva ambas.

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

No uses sudo para la batería completa como primer recurso. Algunas pruebas usan puertos locales y una base OVS temporal propia. Antes del ejecutor QA se obtuvieron 187 casos: 186 correctos y uno omitido. Después de añadir las 11 pruebas del ejecutor, la última batería fue de **198 casos: 197 correctos y uno omitido por requerir sudo**. El nombre exacto de la omitida está en la sección 16.

Estos comandos se conservan como instrucciones de reproducción futura. **No se vuelven a ejecutar por el hecho de actualizar o leer este documento**; el usuario decidió detener nuevas rondas QA.

Para ejecutar solamente las pruebas nuevas más relevantes:

```bash
python3 -m unittest escenarios.test_progreso controlador.test_topologia demo.test_orquestador demo.test_red demo.test_qa_sprint3
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
| `datos/qa/<fecha-UTC>/` | Evidencias y resultados detallados de cada intento QA. |
| `ci/evidencias/qa-sprint3.json` | Resumen QA publicado y ordenado; no se actualiza automáticamente con cada corrida. |

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

### 9.2 Primera comparación: resultados de las seis fases

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

### 9.4 Qué conclusión es defendible al considerar ambas comparaciones

En la **primera comparación**, prioridad mantuvo voz, pagos y web dentro de los objetivos durante el respaldo, mientras la referencia sin QoS quedó fuera de ellos. En la **comparación de cierre QA**, mejoró la latencia de esos servicios y pagos/web cumplieron sus objetivos, pero voz y video incumplieron el objetivo de pérdida; voz también incumplió MOS. Se comprobó una base funcional, con un hallazgo de calidad pendiente. No es correcto generalizar la primera corrida ni ocultar la segunda.

No acredita por sí solo que el sistema funcione igual en cualquier empresa, carga, hardware o red real de producción. Tampoco demuestra causalidad individual de cada mecanismo: `sin_qos` y `prioridad` difieren en clasificación y organización de colas. Para aislar el efecto de clasificar respecto de tener filas cortas, `fila_corta` es una referencia útil que todavía debes ensayar con ese propósito.

No se hizo una campaña estadística repetida en esta sesión. La misma semilla reproduce el plan de carga; no garantiza tiempos idénticos del kernel y del transporte.

### 9.5 Comparación completa durante el cierre QA

Se utilizó el mismo escenario, Sala 1, semilla 7, ruido 0 y escala 1. Esta ejecución comenzó después de cancelar una corrida con tráfico; no se trata de valores recalculados de la primera comparación.

| Estrategia | Fase | Voz p95 ms | MOS | Pagos p95 ms | Web p95 ms | CPU % | Válida por CPU |
|---|---|---:|---:|---:|---:|---:|---|
| sin_qos | normal | 98,04 | 4,35 | 216,1 | 573,0 | 24,6 | Sí |
| sin_qos | respaldo | 423,01 | 2,92 | 848,3 | 5709,8 | 39,9 | Sí |
| sin_qos | normal_otra_vez | 96,12 | 4,35 | 51,1 | 401,9 | 32,7 | Sí |
| prioridad | normal | 11,61 | 4,40 | 32,4 | 356,1 | 32,5 | Sí |
| prioridad | respaldo | 16,65 | 3,20 | 34,9 | 2362,1 | 45,8 | Sí |
| prioridad | normal_otra_vez | 17,67 | 4,39 | 37,9 | 391,1 | 63,1 | Sí |

Durante `prioridad/respaldo`, la pérdida de voz fue **10,82 % en subida y 12,04 % en bajada**; el resumen conserva el peor sentido, 12,04 %. El jitter resumido fue 9,62 ms. El cumplimiento de voz fue `no (pérdida, MOS)` y el de video `no (pérdida)`. Pagos y web sí cumplieron.

Una fase válida por CPU puede incumplir objetivos de servicio. Tampoco significa que CPU media baja descarte cualquier limitación del host, de memoria, planificación o colas. La causa concreta de esta pérdida no se diagnosticó; no hay evidencia para atribuirla automáticamente a Docker, a Mininet o a una regla particular.

El resultado funcional QA `APROBADO_CON_PENDIENTES` significa que se ejecutaron los flujos y se conservaron mediciones coherentes. **No certifica que prioridad alcance todos los objetivos QoS en todas las fases.**

### 9.6 Ubicación y separación de las mediciones

- `outputs/demo-real/comparacion-respaldo.json` y las capturas iniciales corresponden a la primera comparación.
- `datos/qa/20261027T035947.307226Z/comparacion.json` corresponde a la comparación de cierre QA.
- `ci/evidencias/qa-sprint3.json` reúne los resultados funcionales, las métricas resumidas, el cumplimiento de servicio y el hallazgo `QOS-01`.
- El `demo.csv` local actual conserva las 9 filas iniciales más 6 del cierre QA: **15 en total**. La cancelación probada no añadió un conjunto completo de fases a ese CSV.
- `datos/progreso.json` contiene el último progreso guardado; al cerrar esta revisión seguía mostrando la comparación QA terminada. No contiene el histórico completo de todas las corridas.

## 10. Qué mostrar y cómo explicarlo al profesor

### 10.1 Mensaje principal

Puedes explicarlo con tus propias palabras a partir de este texto:

> Nuestro avance consiste en una red empresarial virtual con cinco sedes y un controlador SDN. Generamos tráfico para observar qué ocurre cuando un respaldo compite con voz, pagos y navegación. Comparamos una referencia sin QoS con una estrategia que clasifica por destino y aplica colas por clase. En dos comparaciones observamos menor latencia con prioridad. La primera cumplió los objetivos de los servicios evaluados durante el respaldo; la segunda detectó pérdida de voz y MOS insuficiente, que registramos como trabajo pendiente. La consola permite ver switches, reglas, colas y mediciones reales. También verificamos la cancelación y el arranque repetido de la red. La IA sigue prevista para una etapa posterior.

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
| Cierre | Presentas alcance y próximos pasos. | Investigar pérdida de voz, campañas repetidas, robustez e IA; CI/CD preparado, no acreditado en Azure aquí. |

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
| No hay decisiones nuevas sin tráfico. | En reposo puede ser normal. El último estado tenía clasificador `ninguno`; los escenarios eligen su estrategia. Para revisar reglas anticipadas, selecciona conscientemente `destino` sin un escenario activo. |
| No aparece `set_queue` después de reiniciar Ryu. | Un controlador recién iniciado usa `ninguno`. La existencia de colas HTB no activa por sí sola la clasificación. QA activa `destino` antes de esa consulta. |
| La API devuelve 503 justo después de limpiar Mininet. | Se observó una interrupción transitoria de Ryu incluso en Docker. Espera la recuperación y revisa registros si persiste; no interpretes una API caída como cero switches. |
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

Si una red gestionada quedó colgada, usa Limpiar todo desde la consola y revisa el mensaje. No utilices `sudo mn -c` indiscriminadamente mientras hay una corrida en curso: limpia recursos globales de Mininet y puede afectar controladores. **En este Ubuntu se observó que la limpieza también alcanzó temporalmente Ryu dentro de Docker.** La política de reinicio recuperó el contenedor, y el script QA espera la API con un límite. Docker no garantiza que la limpieza del host sea inocua para el controlador.

## 13. GitHub: commits, rama y confirmación sobre main

### 13.1 Respuesta directa

**Antes de esta actualización había nueve commits publicados en `demo-consola`: seis de integración/implementación/validación, uno de documentación inicial y dos de QA y ordenamiento. Esta revisión documental se añade como décimo commit sobre la base original.**

**Sí: se utilizó `main` como punto de partida para clonar la base.**

**No: no se movió la referencia de `main`, no se hizo merge y no se publicaron cambios sobre ella.**

Trabajar en una rama utiliza archivos en la misma carpeta de trabajo de Git, pero los commits se asignan a la rama activa. Modificar esos archivos mientras está activa `demo-consola` no modifica automáticamente la referencia de `main`.

### 13.2 Historial completo de entregas

| Orden | Commit | Propósito |
|---|---|---|
| 1 | `88731a8` | Integrar la base Sprint 3: panel, CI/CD, Docker y especificación. |
| 2 | `6f90133` | Progreso de escenarios y resultados separados de demo. |
| 3 | `4813fc4` | API de topología y red en reposo con limpieza al detener. |
| 4 | `6b6bddb` | Orquestador y consola de cuatro vistas. |
| 5 | `3febeb2` | Elegir modo Docker al arrancar sin editar la configuración guardada. |
| 6 | `0f7968c` | Documentar la validación real y ajustar indicadores de la consola. |
| 7 | `d3fa14f` | Primera versión de este contexto completo y guía de demo. |
| 8 | `17bab70` | Script QA ejecutable, sus 11 pruebas nuevas y resultados reales en JSON. |
| 9 | `0003eca` | Registro QA ordenado por códigos únicos, conservando el orden real de ejecución. |
| 10 | Consultar el commit de esta revisión | Actualizar este Markdown con toda la historia, QA, hallazgos, reproducción y contexto para retomar. |

Enlaces:

- [Rama demo-consola](https://github.com/mort1zr/qos-adaptativa/tree/demo-consola).
- [Historial de demo-consola](https://github.com/mort1zr/qos-adaptativa/commits/demo-consola/).
- [Comparación entre main y demo-consola](https://github.com/mort1zr/qos-adaptativa/compare/main...demo-consola).
- [Documento de validación publicado](https://github.com/mort1zr/qos-adaptativa/blob/demo-consola/docs/VALIDACION_LOCAL.md).

Los commits 7 y 10 documentan el trabajo. No representan implementaciones nuevas de IA ni nuevas mediciones. El commit 9 modifica solamente el registro JSON: ordena los casos y añade `orden_ejecucion`; no vuelve a probar la red.

Para ver el hash del commit que contiene esta revisión, sin introducir una autorreferencia imposible dentro de su propio contenido:

```bash
git log -1 --format='%h %s' -- docs/CONTEXTO_COMPLETO_Y_GUIA_DEMO_QOS.md
```

No se creó un pull request ni se realizó una fusión.

### 13.3 Referencias verificadas al comenzar esta actualización

```text
main:
86782458ae549a68a46e92102a7c8959065a6ddc

demo-consola, antes del nuevo commit documental:
0003ecadc7826794c98aa62b00d7a6f47623139c
```

Estas referencias se comprobaron localmente y mediante `git ls-remote` en GitHub el 26/10/2026 a las 23:27, hora de Lima. El árbol de trabajo estaba limpio y `demo-consola` sincronizada con `origin/demo-consola`. La actualización de este Markdown cambia después la punta de `demo-consola`; no modifica `main` ni el código de ejecución del laboratorio.

En `0003eca`, el diff respecto de `8678245` abarcaba **40 archivos**, incluidos este Markdown, el script QA, sus pruebas y el JSON. Esta revisión edita un archivo ya existente. Son cambios de la rama de demo; no se fusionaron en `main`.

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

El repositorio pertenece a `mort1zr`. La cuenta colaboradora utilizada fue `fabalonso`, con autor local de Git `Fabian Mansilla` y correo de privacidad de GitHub. La autorización de acceso se completó mediante el flujo de dispositivo que el usuario confirmó personalmente. Se usó una copia auxiliar de GitHub CLI; su disponibilidad en esta sesión no garantiza que el comando `gh` esté instalado globalmente en otra terminal o VM.

No se necesita autenticación GitHub para generar tráfico dentro de una copia ya preparada. Para publicar nuevos commits desde otra sesión o equipo se debe verificar la autenticación propia; no se incluyeron secretos en estas instrucciones.

Este Markdown se conserva en `outputs` como entregable local y en `docs/CONTEXTO_COMPLETO_Y_GUIA_DEMO_QOS.md` como fuente versionada. Su primera entrega fue el séptimo commit, `d3fa14f`; la presente revisión añade todo lo ocurrido después. La publicación del documento no convierte el contenido del chat ni los CSV ignorados en archivos automáticamente sincronizados.

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
- `comparacion-respaldo.json`: progreso y métricas de la primera comparación, anterior al cierre QA.
- `enlace-degradado.json`: métricas de la corrida que incluyó una fase inválida.
- `demo.csv` y `demo_contexto.csv`: copias de las nueve filas iniciales y su contexto; no incluyen las seis filas QA posteriores.
- `switches-sala1.txt`, `reglas-sala1.txt`, `colas-sala1.txt`, `qos-sala1.txt`: consultas reales guardadas.
- `topologia.json`: estructura real observada desde la API.
- Capturas del mapa, tráfico y resultados.

El archivo `outputs/respaldo-demo-real.zip` agrupa las evidencias de esa carpeta. Los scripts `preparar-ubuntu-demo.sh` e `iniciar-demo-real.sh` están directamente en `outputs` y contienen las acciones explicadas en este documento.

Estos respaldos son fotografías de la validación realizada, no se actualizan automáticamente cada vez que practicas.

Después del cierre QA se añadió también:

```text
outputs/QA_SPRINT3.json
```

Es la copia de entrega del registro `ci/evidencias/qa-sprint3.json`, con los códigos ordenados y el orden de ejecución original. Las evidencias detalladas de los tres intentos están en `qos-adaptativa/datos/qa/`; no se incluyeron automáticamente en el ZIP inicial ni se subieron todas a GitHub.

### 15.2 Para continuar en otra conversación

Puedes compartir este archivo y resumir el punto de continuación así:

> Proyecto qos-adaptativa en Ubuntu 22.04/VirtualBox. Usar la copia local indicada en esta guía y la rama demo-consola; main sigue en 8678245 sin merge. Último commit anterior a esta revisión: 0003eca; este Markdown se actualizó después mediante otro commit documental. Ryu corre en Docker; Mininet/OVS/HTB en el host; el orquestador se inicia con --controlador docker en localhost:8090. Se comprobaron 44 switches y 276 equipos. Se hicieron dos comparaciones completas de respaldo_en_atencion, Sala 1, sin_qos contra prioridad: en la primera voz pasó de 394,24 a 13,97 ms con MOS 4,4; en la segunda, de 423,01 a 16,65 ms, pero prioridad tuvo pérdida de voz de 12,04 % y MOS 3,2, hallazgo QOS-01 pendiente. Última batería: 198 pruebas, 197 aprobadas y 1 omitida. QA ejecutable dejó 11 comprobaciones funcionales aprobadas y QA-09 no ejecutado; cancelación en 21 s y segundo arranque comprobados. Hay 15 filas de demo locales; el respaldo ZIP inicial conserva solo las primeras 9. IA, Azure DevOps ejecutado, reinicio completo de Ubuntu/orquestador y aceptación completa siguen pendientes. El usuario decidió no ejecutar más QA por ahora: no lanzar nuevas rondas sin una nueva petición. Antes de actuar, consultar estado y cambios locales, preservar datos históricos y leer la sección 20.

### 15.3 Preparación final antes de presentar

1. Abre Ubuntu y confirma que no esté pausada la VM.
2. Cierra aplicaciones innecesarias para dejar recursos al laboratorio.
3. Comprueba que la consola sea real y que el controlador responda.
4. Repasa el recorrido y las opciones del escenario. Si decides ejecutar otra medición en el futuro, identifícala como una corrida nueva; no se inició otra por esta revisión documental.
5. Verifica los indicadores de validez, no solo los colores de los números.
6. Ten a mano este documento, los CSV y las capturas.
7. Presenta resultados observados y límites con transparencia.
8. Explica el siguiente paso de IA como trabajo futuro sobre una base ya funcional.

**Conclusión que puedes sostener:** se integró y verificó una base funcional de red SDN y QoS con una consola, tráfico, mediciones y QA reproducible. En las dos comparaciones se observaron reducciones de latencia con prioridad. La última también mostró pérdida de voz y MOS insuficiente, conservados como hallazgo. La generalización estadística, el diagnóstico de esa pérdida, la robustez completa, la ejecución del pipeline en Azure y la IA siguen siendo trabajo adicional.

## 16. Cierre QA: script, códigos únicos, intentos y evidencias

### 16.1 Por qué se hizo y qué pidió el usuario

Después de las primeras pruebas reales, el usuario preguntó si convenía cerrar el sprint con QA y registrar ese trabajo en su rama. Primero pidió conocer los casos antes de ejecutarlos. Luego pidió que las pruebas fueran un **script**, no otro archivo Markdown, para que la entrega contuviera trabajo ejecutable.

Se implementó un ejecutor real, acompañado de pruebas de su propio validador. Los resultados se publicaron como JSON. La actualización de contexto que estás leyendo se solicitó después y tiene otra finalidad: permitir continuar el trabajo sin perder su historia.

Al terminar las pruebas, el usuario decidió no hacer más QA. No se eliminó el ejecutor ni se revirtieron sus commits; se detuvieron nuevas rondas. Ordenar el registro y actualizar este documento no ejecutan esas pruebas otra vez.

### 16.2 Los tres archivos entregados para QA

| Archivo | Qué contiene | Qué no debe suponerse |
|---|---|---|
| `demo/qa_sprint3.py` | Comprobaciones de entorno, batería automatizada y, con `--red`, acciones sobre el laboratorio real. | No es un generador de resultados ficticios ni una prueba de reinicio completo de Ubuntu. |
| `demo/test_qa_sprint3.py` | 11 pruebas del validador y de las protecciones del ejecutor. | Sus datos sintéticos son fixtures de pruebas, no resultados experimentales del proyecto. |
| `ci/evidencias/qa-sprint3.json` | Registro publicado: resultados reales, métricas, cumplimiento de servicios, hallazgos, intentos previos y límites. | No es un resultado actualizado automáticamente al abrir la página ni al correr de nuevo el script. |

El script tiene permiso de ejecución en Git. La forma explícita utilizada fue `/usr/bin/python3 demo/qa_sprint3.py --red`, desde la raíz del repositorio y **como usuario normal**. Los privilegios de Mininet y Docker los administra el orquestador real que el usuario ya había iniciado con sudo.

### 16.3 Códigos únicos y resultados finales, ordenados

| Código | Nombre / propósito | Qué se hizo realmente | Resultado registrado |
|---|---|---|---|
| **QA-00** | Laboratorio disponible para QA | Confirmar consola real, modo Docker, API disponible y ausencia de un escenario ajeno. Registrar el estado inicial y detener la red en reposo de la consola. | **APROBADO**. Se observó y toleró la recuperación transitoria de la API tras limpiar. |
| **QA-01** | Entorno y rama | Confirmar `demo-consola`, Python, importación de Mininet/PyYAML y disponibilidad de Git, Docker Compose, OVS, `tc` e iperf3. Registrar hashes Git de referencia. | **APROBADO**. |
| **QA-02** | Pruebas automatizadas | Ejecutar el descubrimiento del proyecto mediante `ci/pruebas_junit.py`; conservar XML y log. | **APROBADO**: 198 pruebas, 0 fallos, 0 errores y 1 omitida. |
| **QA-03** | Reinicio del controlador y acceso a HTML | Detener e iniciar Docker mediante la API del orquestador y consultar el HTML de consola y panel. | **APROBADO**. No reinició el proceso del orquestador. |
| **QA-04** | Red e inventario | Levantar la red y esperar a que el estado y el inventario concordaran. | **APROBADO**: 44 switches conectados, 276 equipos, 5 sedes y 8 servidores de Internet simulado. |
| **QA-05** | Reglas, colas y QoS | Activar `destino` y consultar switches, reglas, clases HTB y QoS para Sala 1. | **APROBADO**: evidencias con `is_connected`, `set_queue:`, `class htb` y `linux-htb`. |
| **QA-06** | Comparación completa después de cancelar | Ejecutar `respaldo_en_atencion`, Sala 1, `sin_qos` y `prioridad`, sin modo rápido; revisar seis fases y sus seis filas CSV nuevas. | **APROBADO funcionalmente**, sin fases inválidas por CPU. El incumplimiento de voz se conserva como `QOS-01`. |
| **QA-07** | Cancelar tráfico y rechazar acciones incompatibles | Cancelar después de observar una fase con tráfico; comprobar las protecciones y la limpieza. | **APROBADO**: cancelación en 21,0 s y cero switches conectados al finalizar la limpieza. |
| **QA-08** | Apagado y segundo arranque de la red | Levantar, apagar y volver a levantar la red sin reiniciar Ubuntu ni el orquestador. | **APROBADO**: 2 arranques de red y 44 switches conectados al final. |
| **QA-09** | Reinicio de Ubuntu y del proceso del orquestador | No se ejecutó: apagar la VM o el servidor cortaría la sesión desde la que se estaba trabajando. | **NO_EJECUTADO**. Reiniciar solo Docker no acredita este caso. |
| **QA-REST** | Restaurar el estado inicial del laboratorio | Conservar o restaurar red en reposo según el estado inicial y devolver el clasificador a su selección original. | **APROBADO**. La red quedó levantada; el clasificador consultado después fue `ninguno`. |
| **QA-HASH** | Integridad de archivos protegidos | Comparar SHA-256 antes y después de los archivos rastreados seleccionados de políticas, topología, YAML de escenarios y resultados históricos. | **APROBADO**: 21 archivos conservaron su contenido. |

Son **12 registros de caso**, de los que **11 se ejecutaron y aprobaron funcionalmente** y **1 no se ejecutó**. No deben confundirse con las 198 pruebas unitarias/integradas de código que se ejecutan dentro de QA-02.

La única prueba de código omitida fue:

```text
escenarios.test_escenarios.Csv.test_el_archivo_vuelve_al_usuario_de_sudo
Motivo: solo con sudo
```

No se volvió a ejecutar toda la batería como root para forzar esa prueba a aparecer aprobada. Las otras pruebas de OVS disponibles utilizaron una base temporal propia.

### 16.4 Orden por código y orden real de ejecución

El registro publicado muestra los casos por código. Ese orden facilita encontrarlos, pero no describe la secuencia exacta del experimento. El campo `orden_ejecucion`, añadido en `0003eca`, conserva esta secuencia:

```text
QA-01 -> QA-02 -> QA-00 -> QA-03 -> QA-04 -> QA-05
      -> QA-07 -> QA-06 -> QA-08 -> QA-REST -> QA-HASH -> QA-09
```

**QA-07 ocurrió antes de QA-06** para comprobar que, después de cancelar tráfico, podía completarse otra comparación. QA-09 aparece al final como constancia de un caso no ejecutado, no como una acción realizada.

El commit `0003eca` no alteró los contenidos de los casos, tiempos, métricas, estados o hallazgos. Se comprobó la igualdad de esos datos antes y después de ordenar el JSON, su validez sintáctica y la correspondencia de los hashes de los archivos QA.

### 16.5 Los tres intentos, sin ocultar los fallos iniciales

Horas expresadas en **America/Lima, UTC−5**, del 26/10/2026:

| Intento | Inicio–fin en Lima | Directorio local, nombrado en UTC | Resultado |
|---|---|---|---|
| 1 | 22:55:05–22:55:55 | `datos/qa/20261027T035505.970602Z/` | FALLIDO: 3 aprobados, 2 fallidos, 7 no ejecutados. |
| 2 | 22:57:21–22:58:58 | `datos/qa/20261027T035721.027532Z/` | FALLIDO: 7 aprobados, 1 fallido, 4 no ejecutados. |
| 3 | 22:59:47–23:13:14 | `datos/qa/20261027T035947.307226Z/` | APROBADO_CON_PENDIENTES: 11 aprobados y 1 no ejecutado. |

La última ronda completa duró aproximadamente **13 minutos y 27 segundos**. Incluye pruebas automatizadas, detenciones, reinicio de Docker, armado de redes, cancelación, comparación y segundo arranque. No es una promesa de que cada ejecución vaya a durar lo mismo, ni debe confundirse con la duración de una única demo.

En el **primer intento**, después de detener y limpiar la red, `/qos/estado` respondió 503. La limpieza de Mininet pudo alcanzar el proceso `ryu-manager` incluso dentro del contenedor. Docker lo recuperó mediante su política de reinicio. La primera versión del guion interpretaba esa indisponibilidad transitoria como fallo inmediato y también falló al intentar restaurar el estado.

Se cambió el ejecutor para esperar con un límite a que la API volviera a responder. Un 503 no se trata como una lista vacía de switches. Otros errores HTTP se siguen reportando; no se ocultan indiscriminadamente.

En el **segundo intento**, la red llegó a 44/44, pero la consulta de reglas no contenía `set_queue:`. Después de reiniciar el controlador, el clasificador por defecto era `ninguno`. Las colas HTB existían, pero el guion asumía una selección previa de `destino` que ya no estaba activa.

Se corrigió la preparación de QA-05 para seleccionar `destino` explícitamente y esperar las reglas antes de consultarlas. El ejecutor también conserva y restaura la selección inicial del clasificador al terminar.

En el **tercer intento**, las comprobaciones funcionales se completaron. Los dos intentos fallidos permanecen en `intentos_previos` del JSON publicado. No se corrigió la realidad editando sus resultados; se corrigió el guion y se realizó otra ejecución identificada.

### 16.6 Hallazgos y su estado exacto

| ID de hallazgo | Estado | Descripción |
|---|---|---|
| **QOS-01** | **PENDIENTE_DE_INVESTIGACION** | En `prioridad/respaldo`, pérdida de voz 12,04 %, MOS 3,2 y latencia p95 16,65 ms. Mejora de latencia respecto de `sin_qos` sin cumplimiento completo de voz. La causa no está establecida. |
| **QA-GUION-01** | CORREGIDO_Y_VERIFICADO | Espera acotada de recuperación de API después de la limpieza; no equiparar API caída con red desconectada. |
| **QA-GUION-02** | CORREGIDO_Y_VERIFICADO | Preparar explícitamente `destino` antes de exigir reglas `set_queue` y restaurar la selección original. |

Los IDs de hallazgo son distintos de los IDs de caso de prueba. `QOS-01` no es la prueba QA-01. La existencia de once aprobados funcionales no cierra automáticamente `QOS-01`.

No se cambiaron políticas, umbral de CPU, objetivos de MOS ni cálculos de medición para eliminar la pérdida observada. No hay todavía una corrección del mecanismo de voz respaldada por una nueva campaña.

### 16.7 Qué protecciones incorpora el ejecutor

- Usa la API fija de `http://127.0.0.1:8090`; no recibe un servidor remoto arbitrario como argumento.
- Se ejecuta como usuario normal y exige el entorno Linux del laboratorio.
- Usa un bloqueo local en `datos/qa/ejecucion.lock` para impedir dos instancias de ese ejecutor a la vez.
- Antes de intervenir exige consola real, modo Docker, API disponible y ausencia de un escenario ya en curso.
- No cancela un escenario ajeno para iniciar sus propias pruebas.
- Identifica su trabajo por el campo `inicio`; si otro trabajo lo reemplaza, detiene la prueba en lugar de actuar ciegamente sobre él.
- Tiene tiempos máximos para comandos, consultas, esperas y comparación.
- Conserva logs y evidencia por intento y hace una restauración al finalizar.
- Compara el prefijo anterior del CSV y exige exactamente seis filas nuevas de la comparación prevista.
- Contrasta métricas del CSV con las del progreso y rechaza datos incompletos, no finitos o de otra sala/escenario.
- No convierte CPU desconocida en una medición válida ni fases con CPU desde 90 % en aprobados experimentales.
- Verifica hashes de archivos protegidos, sin incluir los CSV de demo ignorados como si fueran históricos inmutables.

Estas protecciones no convierten la limpieza global de Mininet en una operación aislada de cualquier otro laboratorio del host. Durante una ejecución real no deben usarse simultáneamente los botones de la consola ni arrancarse otra red manual.

### 16.8 Las 11 pruebas nuevas del propio ejecutor

El archivo `demo/test_qa_sprint3.py` comprueba:

1. Aceptar seis fases completas con CSV coincidente.
2. Marcar CPU desde 90 % como resultado inconcluso.
3. Respetar una fase marcada inválida aunque su CPU numérica sea menor.
4. Rechazar CSV incompleto, duplicado o con métricas divergentes.
5. Rechazar métricas ausentes, NaN/infinito o ausencia de transacciones.
6. Rechazar progreso cancelado o sala incorrecta.
7. No interpretar una API temporalmente caída como una red limpia.
8. No ocultar otros errores de API al esperar limpieza.
9. No cancelar un escenario ajeno durante la preparación.
10. No detener un trabajo que fue reemplazado fuera del script.
11. No convertir un caso inconcluso en aprobado.

Los fixtures están identificados en el código como sintéticos. Sus cifras no aparecen en las tablas experimentales de esta guía ni sustituyen los CSV reales.

La evolución de la batería durante este trabajo fue: 151 y después 155 casos en etapas iniciales; 187 tras la consola y sus integraciones; 196 con los primeros nueve casos del ejecutor; **198** después de añadir las comprobaciones sobre recuperación y errores de API. Las cifras de cada etapa son históricas, no resultados simultáneos de una sola ejecución.

### 16.9 Cómo ejecutar el script en el futuro, solo si vuelves a decidirlo

**No ejecutar ahora por defecto:** el usuario indicó que no haría más QA. Los comandos siguientes se documentan para una decisión futura y explícita.

Con la terminal situada en la raíz del repositorio:

```bash
/usr/bin/python3 demo/qa_sprint3.py --help
```

Modo básico, para entorno y batería de código, sin solicitar las acciones reales de red del ejecutor:

```bash
/usr/bin/python3 demo/qa_sprint3.py
```

Modo completo, con el orquestador real y controlador Docker ya disponibles:

```bash
/usr/bin/python3 demo/qa_sprint3.py --red
```

`--red` detiene y reconstruye redes, reinicia el controlador Docker, genera tráfico, cancela un escenario y ejecuta otra comparación. No lo uses durante una presentación ni mientras otra persona está haciendo una medición. Puede agregar nuevas filas a `demo.csv`; no es una consulta de lectura.

El modo básico no acredita los casos de red omitidos. El modo completo sigue sin apagar Ubuntu ni relanzar el proceso del orquestador.

| Código de salida | Significado |
|---|---|
| `0` | Los casos ejecutados aprobaron; puede seguir habiendo casos no ejecutados y objetivos de servicio incumplidos. |
| `1` | Falló alguna comprobación funcional o de preparación. |
| `2` | No hubo fallo funcional, pero la evaluación encontró mediciones inconclusas, por ejemplo por CPU. |

El JSON usa estados como `APROBADO`, `FALLIDO`, `INCONCLUSO` y `NO_EJECUTADO`. La ronda final guardó el resumen global `APROBADO_CON_PENDIENTES`.

**Un código 0 no es una certificación de todos los objetivos de voz/video**, ni de toda la sección 6.2 de la especificación. Es necesario leer también `objetivos_de_servicio` y `hallazgos` del registro publicado o las métricas completas del intento local.

### 16.10 Dónde quedó la evidencia y cómo leerla sin repetir QA

Registro publicado:

```text
ci/evidencias/qa-sprint3.json
```

Evidencia detallada de la última ejecución:

```text
datos/qa/20261027T035947.307226Z/
  unitarias.xml
  unitarias.log
  topologia.json
  evidencia-switches.json
  evidencia-reglas.json
  evidencia-colas.json
  evidencia-qos.json
  telemetria-antes-cancelar.json
  comparacion.json
  filas-nuevas.json
  resumen.json
```

Los intentos fallidos contienen únicamente los archivos que llegaron a generarse antes del fallo. No se deben inventar archivos ausentes como si las etapas posteriores se hubieran ejecutado.

Este comando solo lee el registro publicado y muestra los códigos; **no ejecuta el script QA**:

```bash
/usr/bin/python3 - <<'PY'
import json
from pathlib import Path
d = json.loads(Path('ci/evidencias/qa-sprint3.json').read_text())
for caso in d['resultado_funcional']['casos']:
    print(caso['id'], caso['estado'], caso['nombre'])
print('Hallazgos:')
for hallazgo in d['hallazgos']:
    print(hallazgo['id'], hallazgo['estado'], hallazgo['descripcion'])
PY
```

Los JSON originales guardados en `datos/qa/` conservan el orden de la ejecución; el JSON publicado incorpora después el ordenamiento pedido. No tienen que ser idénticos byte a byte para representar las mismas mediciones.

Dentro de QA-01 se registró Git `d3fa14f`, porque los archivos del ejecutor aún no se habían confirmado como `17bab70` al ejecutar las pruebas. Eso es un dato de procedencia histórico, no una referencia que se deba editar al último commit. `fuentes_qa_sha256` identifica el contenido del ejecutor y sus pruebas probado durante esa ronda.

## 17. GitHub, copia local, VS Code y reproducción en otra VM

### 17.1 De dónde lee realmente el código la demo

GitHub conserva una copia versionada del código. Al clonar se descargan los archivos a Ubuntu. A partir de allí, el laboratorio ejecuta **la copia local**:

```text
GitHub, rama demo-consola
    -> git clone o git pull
    -> archivos del repositorio en Ubuntu
    -> Docker construye/ejecuta Ryu y el orquestador carga su configuración
    -> el orquestador sirve demo/consola/index.html
    -> el navegador abre http://127.0.0.1:8090
```

El HTML sí está en GitHub, en `demo/consola/index.html`. El navegador lo recibe del servidor local, no de GitHub Pages. No se publicó esta consola como un sitio público en Internet.

La aplicación no consulta GitHub continuamente ni se actualiza sola al publicar un commit. La base de datos, inventarios, progreso y resultados de demo se generan localmente. La imagen Docker y los paquetes del sistema tampoco se descargan automáticamente por clonar el repositorio.

Después de preparar las herramientas y la imagen, el tráfico ensayado ocurre dentro del laboratorio. La consola utiliza recursos locales y no depende de CDN; no se hizo en QA una campaña específica apagando toda conectividad externa. Las descargas iniciales y las operaciones con GitHub sí necesitan conexión.

### 17.2 Ruta exacta de tu copia local

```text
/home/elonmusk/Documents/Codex/2026-10-26/referenced-chatgpt-conversation-this-is-an/qos-adaptativa
```

La carpeta `outputs` es hermana del repositorio, no una carpeta que se clone desde GitHub:

```text
/home/elonmusk/Documents/Codex/2026-10-26/referenced-chatgpt-conversation-this-is-an/
  qos-adaptativa/   código y documentación versionados
  outputs/         entregables, scripts locales y capturas
  work/            material auxiliar de trabajo y herramientas
```

No copies indiscriminadamente `work` a un repositorio público: puede incluir material de autenticación y herramientas auxiliares. Este documento no contiene tokens, contraseñas ni códigos de autorización.

### 17.3 Utilizar Visual Studio Code

Abre VS Code dentro de Ubuntu y selecciona **Archivo → Abrir carpeta → qos-adaptativa**. Alternativa, si el comando `code` está disponible:

```bash
code "/home/elonmusk/Documents/Codex/2026-10-26/referenced-chatgpt-conversation-this-is-an/qos-adaptativa"
```

Puedes ejecutar los comandos de arranque en **Terminal → Nueva terminal**. Usa otra terminal integrada si necesitas consultas mientras el orquestador permanece en primer plano.

Mantén el editor como usuario normal. No hace falta ejecutar todo VS Code con sudo. Los comandos administrativos concretos solicitan sudo en su terminal. El Python del sistema debe poder importar Mininet y PyYAML; un entorno virtual cualquiera puede no tener esos módulos.

Para mostrar el avance al profesor:

| En VS Code | Explicación |
|---|---|
| `topologia/empresa_xyz.py` y su YAML | Qué sedes y enlaces construye Mininet. |
| `politicas/politicas.yaml` y `destinos.yaml` | Cómo están definidas las clases, garantías, techos y destinos. |
| `controlador/clasificadores.py` y `qos_app.py` | Cómo se decide una clase y se instala `set_queue`. |
| `escenarios/escenario.py` y `escenarios.yaml` | Cómo se planifican las fases y se generan mediciones. |
| `demo/orquestador.py` e `index.html` | Cómo se convierten las acciones de la página en trabajos controlados. |
| `demo/qa_sprint3.py` y `ci/evidencias/qa-sprint3.json` | Qué QA se automatizó, qué se comprobó y qué quedó pendiente. |
| Historial de Git | Qué entregas se registraron en la rama de demo. |

La interfaz se muestra en el navegador de Ubuntu. No se necesita Live Server ni abrir el HTML como un archivo suelto: la página depende de la API que sirve el orquestador.

### 17.4 Reproducir en otro Ubuntu con los mismos requisitos

No es necesario que esa persona tenga tu mismo nombre de usuario ni este chat. Necesita acceso al repositorio, los paquetes del laboratorio, los módulos de kernel y permisos administrativos para iniciar los procesos de red.

**Estas instrucciones se revisaron contra los archivos del proyecto; no se ejecutaron sobre una segunda VM recién creada durante esta sesión.** El caso de reproducción desde cero en otra máquina sigue siendo una comprobación independiente.

Paso 1. Clonar la rama correcta, usando Git instalado en la VM:

```bash
git clone --branch demo-consola https://github.com/mort1zr/qos-adaptativa.git
cd qos-adaptativa
```

Si el repositorio exige autenticación, la persona debe utilizar su propia cuenta autorizada y aceptar la invitación correspondiente. No debe usar tus tokens ni copiar la carpeta de autenticación de esta sesión.

Paso 2. Si ya tiene los requisitos instalados, iniciar servicios y cargar los módulos:

```bash
sudo systemctl start openvswitch-switch docker
sudo modprobe openvswitch
sudo modprobe sch_htb
sudo modprobe sch_netem
sudo modprobe ifb
```

Si no tiene los requisitos, debe instalar primero Mininet, Open vSwitch, iperf3, iproute2, Docker Engine con `docker compose`, Python del sistema con PyYAML, curl y Git, mediante los repositorios adecuados de su Ubuntu. La lista utilizada en este equipo está en 4.7 y el instalador local en `outputs/preparar-ubuntu-demo.sh`. No se preparó un instalador universal para cualquier versión de Ubuntu.

Paso 3. Preparar datos y construir el controlador desde los archivos clonados:

```bash
mkdir -p datos
sudo docker compose up -d --build
```

La primera construcción puede descargar bastantes datos. El Dockerfile fija un usuario 1000:1000 dentro del contenedor. Si la VM de destino usa otro UID o permisos distintos, revisar el acceso de escritura a `datos` antes de medir; no resolverlo dando permisos globales a toda la carpeta del proyecto.

Paso 4. Iniciar el orquestador con el Python del sistema y modo Docker explícito:

```bash
sudo /usr/bin/python3 -u demo/orquestador.py --controlador docker
```

Dejar esa terminal abierta. Si la API del controlador tarda unos segundos en aparecer, esperar su arranque y revisar `sudo docker compose logs --tail=80 controlador` si no se recupera. No lanzar otro controlador sobre los mismos puertos.

Paso 5. Abrir el navegador **dentro de la nueva VM**:

```text
http://127.0.0.1:8090/
```

Esperar controlador en línea, levantar la red y comprobar el inventario. Para generar una medición, elegir el escenario y las estrategias desde la página. Las cifras nuevas serán de esa VM y deben identificarse como una corrida nueva, sin prometer igualdad con las tablas de este documento.

No es necesario que esa persona ejecute QA completo para abrir la demo. El script QA es una herramienta adicional, disponible si decide utilizarla.

### 17.5 Qué llega al clonar y qué no

| Elemento | ¿Llega con el repositorio? | Acción si hace falta |
|---|---|---|
| Código Python, HTML, YAML y Dockerfile | Sí, al clonar `demo-consola`. | Usar la rama correcta. |
| Script QA y registro JSON publicado | Sí. | Leerlos; ejecutar QA solo si se decide hacerlo. |
| Este Markdown versionado en `docs` | Sí. | Consultarlo como contexto. |
| Mininet, OVS, Docker y módulos de kernel | No como instalaciones del host. | Prepararlos en el Ubuntu de destino. |
| Imagen `qos-controlador:local` | No como imagen ya construida. | Construirla con Compose. |
| `datos/`, telemetría y progreso | No; están ignorados por Git. | Se generan localmente o se copian como respaldo si se quiere conservar evidencia. |
| CSV `demo*.csv` | No. | Ejecutar nuevas corridas o transferir las copias de evidencia por separado. |
| Capturas y ZIP de `outputs` | No. | Copiarlos expresamente si se necesitan. |
| Scripts locales `preparar-ubuntu-demo.sh` e `iniciar-demo-real.sh` | No. | Usar los pasos manuales o copiarlos adaptando la ruta. |
| Acceso directo `.desktop` | Hay uno versionado con ruta de esta copia. | Regenerarlo para la nueva carpeta y revisar el modo de controlador. |
| Sesión de navegador, chat y credenciales GitHub | No. | Usar el propio entorno y cuenta. |

### 17.6 Actualizar la copia local cuando cambie GitHub

Un push cambia el remoto; no actualiza otras copias automáticamente. Si en el futuro quieres traer cambios, primero termina cualquier medición y revisa lo que tengas sin guardar:

```bash
git status --short --branch
git switch demo-consola
git pull --ff-only origin demo-consola
```

No uses un reset destructivo para resolver cambios locales sin revisarlos. Si cambió código de `controlador/`, reconstruye la imagen y reinicia el servicio. Si cambió código del orquestador o YAML cargado en memoria, reinicia ese proceso. El HTML de la consola se sirve desde disco; una recarga puede reflejarlo, pero los cambios de backend asociados también necesitan su reinicio.

Las políticas se montan desde el host en modo Compose, aunque Ryu normalmente las carga en memoria; cambiar el YAML no garantiza una recarga automática. En el despliegue `lab` algunas políticas forman parte de la imagen y requieren reconstrucción. Consulta la sección 11 antes de cambiar una política.

## 18. Apagar Ubuntu, conservar el chat y retomar el trabajo

### 18.1 Qué ocurre al apagar la VM normalmente

El apagado normal detiene los procesos de Ubuntu: orquestador, Mininet, tráfico y contenedores en ejecución. La red del laboratorio no sigue generando tráfico con la VM apagada.

El código, commits locales, documentación y resultados ya escritos permanecen en el disco virtual si ese disco se conserva. Borrar la VM con su disco, restaurar una instantánea anterior o perder el archivo del disco son situaciones distintas y pueden eliminar cambios que solo existían allí.

El controlador tiene política Docker `restart: unless-stopped`, pero eso no inicia por sí solo toda la demo: el orquestador y la red de Mininet también deben ponerse en marcha. No se creó un servicio systemd de arranque automático del laboratorio completo.

Guardar el estado o suspender la VM tampoco equivale a haber validado un arranque desde cero. No se usó esa operación para declarar QA-09 aprobado.

### 18.2 Antes de apagar

1. Si hay un escenario activo, cancelar desde la página y esperar el estado final.
2. Si la red en reposo está levantada, pulsar Apagar red y esperar la limpieza.
3. Detener el controlador desde la consola si se quiere dejarlo apagado, sin un trabajo pesado activo.
4. Pulsar Ctrl+C en la terminal donde corre el orquestador en primer plano.
5. Apagar Ubuntu mediante su opción normal de apagado.

No hace falta borrar archivos, imágenes Docker ni instalaciones. Cerrar solamente la pestaña del navegador no detiene el laboratorio.

### 18.3 Volver a arrancar en este mismo equipo

Si la carpeta no se movió, el script local preparado sigue siendo:

```bash
sudo bash "/home/elonmusk/Documents/Codex/2026-10-26/referenced-chatgpt-conversation-this-is-an/outputs/iniciar-demo-real.sh"
```

Ese script utiliza una ruta absoluta de este equipo. Construye o reutiliza la imagen, inicia Docker, espera API y topología, y mantiene el orquestador real en primer plano. Después abre `http://127.0.0.1:8090` en el navegador de Ubuntu y levanta la red desde la página.

Si el script no está disponible, utiliza el arranque manual de 6.4 o 17.4. No necesitas descargar GitHub otra vez para cada encendido.

Al consultar resultados, recuerda que el progreso y CSV pueden corresponder a una corrida anterior guardada. Para demostrar tráfico vivo debes tener un escenario activo y observar sus cambios, no presentar datos guardados como si acabaran de producirse.

### 18.4 Qué se explicó sobre este chat y ChatGPT en el navegador

El usuario abrió ChatGPT en el navegador y no encontró este chat. Se aclaró que esta sesión estaba en **Codex de escritorio con ejecución local**, mientras la conversación inicialmente referenciada era otra conversación llamada **«Evaluación de archivos»**.

No se debe asumir que un chat local de Codex aparecerá automáticamente como la misma conversación en el historial normal de ChatGPT web o de otro dispositivo. El proyecto Git y el historial de conversación son cosas distintas. Publicar un commit tampoco publica el chat completo ni da acceso a la VM desde otro chat.

Se explicó que cerrar la aplicación no equivale a borrar un chat guardado. Para continuar debe abrirse el mismo entorno y localizarse la conversación en la aplicación correspondiente, siempre que sus datos locales se hayan conservado. No se creó un enlace público del chat ni se hizo una migración completa del historial a ChatGPT web.

Este Markdown es el respaldo de contexto más práctico para otra conversación: puede leerse junto con el repositorio. No contiene todas las transcripciones y salidas de herramientas; conserva decisiones, cambios, evidencia y pendientes relevantes. Tampoco da a un nuevo asistente acceso automático a las credenciales o procesos de tu Ubuntu.

### 18.5 GitHub conserva el código; los datos ignorados necesitan otro respaldo

La publicación protege los commits que efectivamente llegaron al remoto. No garantiza conservar `datos/`, los CSV de demo ignorados o los archivos de `outputs` si se pierde la VM.

Para conservar las evidencias de esta sesión fuera del disco virtual hay que transferir expresamente esas carpetas a un almacenamiento elegido por el usuario. No se realizó una copia automática a Google Drive, correo u otro servicio. El ZIP inicial y el JSON de QA existen localmente, y el registro resumido de QA sí está en GitHub.

No uses una copia de las credenciales de GitHub como mecanismo de respaldo del proyecto. La reproducción debe funcionar con la cuenta y permisos de la persona que la realiza.

## 19. Discrepancias, riesgos y límites que deben quedar claros

### 19.1 Documento de especificación frente a implementación y validación

| Punto | Lo propuesto o esperado | Estado real |
|---|---|---|
| ZIP Sprint 3 | Podía parecer un proyecto completo. | Era un paquete parcial de 18 archivos; se necesitó el repositorio base. |
| Consola 8090 | Era una propuesta en la especificación. | Se implementó durante esta sesión; no venía hecha en el ZIP. |
| Panel 8080 | Código incluido en el paquete. | Se integró y conservó, incluso dentro de la pestaña Tráfico. |
| CSV de contexto | La propuesta mencionaba una ruta que no coincidía con el comportamiento habitual. | Se mantuvo `datos/contexto.csv` sin `--salida`; con salida personalizada se usa el sufijo `_contexto.csv`. |
| Evidencia OVS Controller | La especificación usaba la columna `name`. | Se consulta `target,is_connected`, coherente con esa tabla OVS. |
| Telemetría por áreas | El panel mostraba las doce más destacadas. | Se conserva esa salida y se añade `areas_completas` para el mapa. |
| Modo de arranque | `demo.yaml` conserva `lab`. | Esta VM se probó con `--controlador docker`; no se cambió silenciosamente el YAML. |
| Duración del guion | Objetivo de 8 a 10 minutos. | Depende de armado, sondas y recursos. QA completo duró más; no se garantiza un límite de presentación sin ensayarlo. |
| Cancelación | Menos de 30 s y poder ejecutar otra corrida. | Verificado por API: 21 s y comparación posterior completa. No acredita todas las interacciones del mouse ni todos los fallos. |
| Aceptación completa | Lista manual 6.2 y criterios de la sección 7. | Se cubrieron varios casos, pero no se declaró aprobada toda la lista. |
| Mapa | Representar y explorar sedes y segmentos. | Funciona como visualización; no permite arrastrar equipos ni editar enlaces con el mouse. |
| IA adaptativa | Objetivo posterior del proyecto. | Sin modelo entrenado que decida QoS en esta entrega. |

### 19.2 Validez experimental no es cumplimiento de servicio

El criterio de validez por CPU del proyecto descarta fases con CPU media desde 90 %. Esa regla ayuda a señalar saturación del host; no convierte todas las fases restantes en buenos resultados de voz, video o pagos.

En esta sesión hay dos ejemplos diferentes:

- `enlace_degradado/recuperado`: números conservados, pero fase inválida por CPU 92,7 %. No acredita recuperación.
- `prioridad/respaldo` en cierre QA: CPU 45,8 %, fase válida para el criterio aplicado, pero pérdida 12,04 % y MOS 3,2. Es evidencia de un incumplimiento de voz que hay que investigar.

La conclusión correcta necesita revisar validez, configuración, métricas y objetivos. Ni un número verde ni un caso funcional aprobado sustituye esa lectura.

### 19.3 Recursos limitados y comportamiento variable de la VM

Esta VM tiene 3 CPU virtuales y unos 4 GB de RAM. Durante las consultas de cierre tenía memoria de intercambio ocupada; los valores exactos cambian con el tiempo. Reconstruir cientos de enlaces y procesos puede tardar más que lo sugerido por las duraciones de las fases.

La misma semilla reproduce decisiones del plan de carga, no la planificación del kernel, presión de memoria, temporización de TCP ni estado físico del host VirtualBox. No se debe garantizar que otra máquina produzca los mismos decimales o el mismo MOS.

No se hizo una campaña controlada para diagnosticar el origen de la pérdida en QA. Las posibles líneas de investigación no son causas ya demostradas. Tampoco se debe borrar la corrida con pérdida para conservar solo la más favorable.

### 19.4 Limpieza, controladores y configuración inicial

La versión instalada de Mininet incluye `ryu-manager` en los procesos que intenta terminar durante `mn -c`. Docker separa entornos de ejecución, pero en esta prueba no impidió una interrupción transitoria del controlador por la limpieza del host.

El ejecutor QA espera la recuperación de la API. Esto corrige una suposición de su guion; no constituye una implementación nueva de alta disponibilidad de Ryu. Si la API no se recupera dentro del tiempo previsto, debe quedar un fallo y revisarse el controlador.

Una advertencia antigua del Compose sugiere que `mn -c` ya no apaga Ryu al usar Docker. Esa afirmación **no es una garantía válida para este entorno** a la luz del fallo observado. El comportamiento medido y el registro QA tienen prioridad al interpretar esa situación.

Asimismo, el último estado `clasificador: ninguno` no significa que Mininet no tenga red. El clasificador, las reglas OpenFlow y las colas HTB son elementos distintos. Para revisar clasificación por destino hay que seleccionarla; para comparar estrategias hay que dejar que el escenario configure sus mecanismos.

### 19.5 Límites y riesgos del código CI/CD incorporado

Se incorporaron `azure-pipelines.yml` y los scripts de `ci/`, pero no se configuró ni ejecutó aquí una campaña verificable en Azure DevOps. Lo que existe es código preparado, más verificaciones locales de componentes.

Aspectos relevantes de su lectura:

1. El pipeline define calidad, construcción de contenedor, integración opcional y despliegue condicionado. No son etapas ya acreditadas por haber guardado el YAML.
2. La preparación de Python puede omitir una versión que no esté disponible. Es necesario leer las omisiones; una matriz visualmente verde no prueba que se ejecutaron ambas versiones.
3. `ci/integracion.sh` omite la integración con salida 0 si faltan ciertos requisitos, como sudo no interactivo, Mininet o controlador disponible, o si hay conflictos de puertos. Un éxito de ese paso puede ser una omisión informada.
4. La integración del pipeline necesita un agente de laboratorio con permisos definidos. En esta sesión no se modificó sudoers para conceder sudo general sin contraseña.
5. La construcción y el despliegue usan una imagen Docker local. Si etapas o agentes cambian de host, la imagen no se transfiere por sí sola; hace falta revisar la estrategia de publicación o transferencia antes de afirmar que ese pipeline es reproducible entre agentes.
6. El despliegue está condicionado a `main` y a otras condiciones del pipeline. Publicar en `demo-consola` no significa desplegar automáticamente el laboratorio.
7. El modo `lab` usa `qos-controlador-lab`; Compose local usa `qos-controlador`. Compiten por los mismos puertos y no deben levantarse juntos.
8. El script de despliegue contiene un mecanismo de vuelta a una imagen anterior, pero no se probó ese rollback como parte de este cierre.

Estas son observaciones del código y límites de lo verificado, no fallos observados de una ejecución real en Azure. Antes de una exposición cercana se priorizó la red local funcional y el tráfico, conforme al objetivo del profesor. No se movió Mininet a una VM de Azure.

### 19.6 Alcance de seguridad y acceso

El orquestador es un servicio local con acciones administrativas sobre el laboratorio. Valida rutas, parámetros, origen y host, limita consultas y usa comandos definidos. Los puertos del controlador publicados por Compose están enlazados a `127.0.0.1` del host.

Dentro del contenedor Ryu escucha en `0.0.0.0` para recibir el reenvío de puertos; eso no contradice que el acceso publicado en la VM se limite a localhost. Son dos espacios de red distintos.

No se diseñó una aplicación multiusuario pública con cuentas y permisos. No se deben abrir sus puertos a una red externa como si ya contara con esa capa de autenticación. El acceso desde otro equipo requiere un mecanismo apropiado, como el túnel local mencionado en la especificación, y una decisión específica de configuración.

El usuario autorizó la autenticación GitHub y ejecutó los pasos sudo en su propia terminal. No se introdujo su contraseña en código, no se subieron credenciales y no se cambió `main`. El acceso a terminal y navegador utilizado durante la sesión no implica que el proyecto tenga permisos permanentes para controlar cualquier aplicación o dispositivo.

### 19.7 Qué otros documentos son fotografías anteriores

- `docs/VALIDACION_LOCAL.md` refleja la validación anterior al ejecutor QA: sus cifras de 187 pruebas y cancelación pendiente son históricas.
- `outputs/demo-real/INFORME_VALIDACION.md`, las capturas iniciales y `respaldo-demo-real.zip` pertenecen a esa etapa inicial.
- `docs/DESARROLLO_LOCAL.md` se redactó al preparar la base local y contiene referencias al entorno previo a instalar o publicar. No debe usarse para deducir que Docker o Mininet siguen sin instalar en esta VM.
- El presente documento consolidado y `ci/evidencias/qa-sprint3.json` son las referencias para el cierre posterior.

No se reescribieron los informes iniciales para que parecieran generados después de QA. Esta guía explica su alcance y fecha para evitar contradicciones al retomar el trabajo.

## 20. Punto exacto de continuación y transferencia de contexto

### 20.1 Datos que un nuevo colaborador debe conocer primero

| Dato | Valor al cierre documentado |
|---|---|
| Repositorio | `https://github.com/mort1zr/qos-adaptativa.git` |
| Rama de trabajo | `demo-consola` |
| Main de referencia | `86782458ae549a68a46e92102a7c8959065a6ddc`, sin cambios de esta sesión. |
| Último commit antes de actualizar esta guía | `0003ecadc7826794c98aa62b00d7a6f47623139c` |
| Commit técnico de QA | `17bab70d79873beb71ff8f50e5a4c4904cbb8ca8` |
| Commit de implementación/validación real previa | `0f7968c` |
| Estado HTTP consultado | 26/10/2026, 23:27 America/Lima: controlador y red activos, 44/44, modo Docker. |
| Clasificador en esa consulta | `ninguno`, restaurado al estado inicial. |
| Último progreso | Comparación QA terminada; datos guardados, sin escenario activo. |
| CSV local de demo | 15 filas: 3 de degradación, 6 de primera comparación y 6 de cierre QA. |
| Última batería automatizada | 198 pruebas: 197 aprobadas, 1 omitida. |
| Cierre funcional QA | 11 aprobados, QA-09 no ejecutado. |
| Hallazgo técnico abierto | `QOS-01`: pérdida de voz y MOS en `prioridad/respaldo`. |
| Decisión de usuario vigente | No ejecutar nuevas rondas QA por ahora; conservar evidencia y contexto. |
| Objetivo académico | Mostrar una red funcionando con tráfico y explicar su código; IA como trabajo futuro. |

La punta de `demo-consola` cambiará al incorporar esta revisión documental. Utiliza `git log` para consultar su hash actual; no asumas que `0003eca` sigue siendo HEAD después de leer este archivo en el commit nuevo.

### 20.2 Primeros pasos de lectura, sin alterar la red

En una nueva sesión, empieza por confirmar el directorio y revisar el trabajo local:

```bash
cd "/home/elonmusk/Documents/Codex/2026-10-26/referenced-chatgpt-conversation-this-is-an/qos-adaptativa"
git status --short --branch
git log -10 --oneline
git rev-parse HEAD main
```

Si el servidor puede seguir activo, estas consultas son de lectura:

```bash
curl -fsS http://127.0.0.1:8090/demo/estado
curl -fsS http://127.0.0.1:8090/qos/estado
```

Leer después, en este orden:

1. La lectura rápida inicial y las secciones 9, 16 y 20 de este documento.
2. `ci/evidencias/qa-sprint3.json`, incluidos los hallazgos y límites.
3. `demo/demo.yaml` y los argumentos del proceso que se quiera iniciar.
4. El archivo concreto que corresponda al nuevo objetivo: no reconstruir todo el laboratorio sin necesidad.

Si los endpoints no responden, no supongas que el repositorio se perdió ni ejecutes limpieza automática. Comprueba si se apagó Ubuntu o la terminal, y utiliza los pasos de arranque cuando el usuario quiera volver a ejecutar la demo.

### 20.3 Acciones que no forman parte de retomar el contexto

- No arrancar QA solo porque el documento contiene su comando.
- No iniciar un escenario nuevo mientras se está leyendo un resultado anterior.
- No borrar `datos/`, resultados de demo ni archivos históricos para dejar una vista más limpia.
- No convertir QA-09 en aprobado por haber reiniciado únicamente Docker.
- No cerrar `QOS-01` sin diagnóstico y evidencia nueva solicitada.
- No afirmar que hay IA entrenada o pipeline Azure ejecutado por ver los archivos respectivos.
- No mezclar números de la primera comparación con pérdida/MOS de la segunda como si fueran la misma corrida.
- No fusionar ni publicar en `main` como paso implícito de documentación.
- No cambiar límites, políticas o mediciones para conseguir que los resultados aparezcan favorables.
- No subir las credenciales ni la carpeta auxiliar de autenticación al repositorio.

### 20.4 Próximas líneas de trabajo, todavía no ejecutadas

Si el usuario decide continuar desarrollando, las tareas pendientes se pueden escoger por separado:

| Tarea posible | Qué debería producir para considerarse avance real |
|---|---|
| Diagnosticar `QOS-01` | Evidencia que permita ubicar la pérdida, separar posibles causas y justificar una corrección; después una validación nueva autorizada. |
| Completar QA-09 | Reinicio real de Ubuntu y relanzamiento del orquestador siguiendo la guía, con registro de lo observado. |
| Reproducción en otra VM | Instalación o verificación independiente, clone de la rama y una ejecución identificada en ese entorno. |
| Campañas estadísticas | Repeticiones, controles como `fila_corta`, configuración documentada y análisis que no seleccione solo los mejores resultados. |
| Azure DevOps | Organización/proyecto/agente y permisos configurados, pipeline efectivamente ejecutado, logs y omisiones revisadas, transferencia de imagen resuelta. |
| IA | Datos y objetivos definidos, modelo entrenado/evaluado y comparación con estrategias base; no basta con renombrar un perfil. |
| Mejoras de operación | Arranque/recuperación más robustos y documentación de sus límites, sin sustituir las mediciones por valores de ejemplo. |

Estas tareas no se iniciaron al preparar el Markdown y no representan una autorización permanente para ejecutar nuevas pruebas o despliegues. La siguiente petición del usuario determinará cuál corresponde.

### 20.5 Texto de transferencia para una nueva conversación

Puedes copiar este bloque junto con el archivo completo y el enlace al repositorio:

> Continúa el proyecto qos-adaptativa usando este documento como contexto factual. La copia de Ubuntu está en `/home/elonmusk/Documents/Codex/2026-10-26/referenced-chatgpt-conversation-this-is-an/qos-adaptativa`, rama `demo-consola`. Main permanece en `8678245` sin merge. El historial anterior a esta actualización termina en `0003eca`; consulta Git para conocer el commit documental actual. Ryu funciona en Docker, y Mininet/OVS/HTB en el host; el orquestador real usa `--controlador docker` y publica la consola en localhost:8090. A las 23:27 de Lima del 26/10/2026 había 44/44 switches conectados, red en reposo y clasificador `ninguno`. Hay 276 equipos inventariados y 15 filas de demo locales. La última batería tuvo 198 pruebas, 197 aprobadas y 1 omitida. El QA ejecutable dejó 11 casos funcionales aprobados; cancelación en 21 s y ejecución posterior verificadas. QA-09, reinicio completo de Ubuntu/orquestador, sigue no ejecutado. En la segunda comparación hubo pérdida de voz de 12,04 % y MOS 3,2 con prioridad durante respaldo, hallazgo QOS-01 sin causa establecida. La primera comparación había dado MOS 4,4; conserva ambas evidencias, no selecciones solo la favorable. IA y ejecución de Azure DevOps siguen pendientes. El usuario decidió no hacer más QA por ahora. No lances pruebas de red, no borres datos, no cambies main ni supongas permisos heredados del chat. Primero revisa el estado actual y los cambios locales, y atiende la nueva petición concreta.

### 20.6 Qué se actualizó al preparar esta revisión

Se relevaron de nuevo los archivos, el historial Git, el JSON publicado y los CSV locales. Se consultaron, sin acciones de escritura sobre la red, los endpoints de estado y las ramas remotas. Se corrigieron las referencias antiguas a cancelación pendiente, 187 pruebas como cifra final, solo nueve filas y siete commits como total del trabajo.

Se añadieron el cierre QA, los tres intentos, sus códigos y orden real, la segunda comparación completa, el hallazgo de voz, la reproducción en otra VM, las aclaraciones sobre VS Code/GitHub/chat, el apagado y reinicio, los límites de CI/CD y el punto de continuación.

Esta revisión modifica documentación y su copia de entrega. **No se ejecutó otra ronda QA, no se generaron nuevas mediciones, no se modificaron políticas ni código funcional, y no se fusionó la rama con `main`.**
