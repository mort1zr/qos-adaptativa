# Especificación: Consola de demo de QoS adaptativa (Sprint 3)

> **Para quien implementa (persona o IA):** lee este documento completo antes de escribir código.
> Trabaja en el orden de la sección 12, corre las pruebas después de cada paso y no cambies nada
> de lo que la sección 3.4 marca como intocable. Si algo de aquí choca con el código real,
> **manda el código**: anótalo y pregunta antes de "arreglarlo".

| | |
|---|---|
| Proyecto | Proyecto Final de Carrera III · QoS adaptativa con SDN e IA (Empresa XYZ) |
| Repositorio | `github.com/mort1zr/qos-adaptativa` (rama `main`) |
| Base | commit `8678245` + paquete `sprint3-azure-panel` (panel en vivo, CI/CD, Docker) |
| Autor del documento | Aaron Ortiz, con apoyo de Claude |
| Fecha | 26 de octubre de 2026 |
| Entregable | Una consola web donde **toda la demo se maneja con botones**, sin abrir la terminal |

---

## 1. Qué se quiere lograr

En la presentación no basta con mostrar resultados: el público tiene que **ver la red, ver el
entorno funcionando y ver el efecto de la QoS mientras pasa**. Hoy eso exige abrir terminales
(Ryu, Mininet, comandos de `ovs-vsctl`, `tc`), que en una presentación se ve mal y es frágil.

Se construye una **Consola de demo**: una página web con cuatro pestañas.

| Pestaña | Qué muestra | Qué se puede hacer |
|---|---|---|
| **Demo** | Estado del entorno (controlador, red, switches conectados) y el escenario en curso fase por fase, con voz, pagos y web contra su objetivo | Botones: iniciar/detener controlador, levantar/apagar la red, correr un escenario, comparar dos estrategias, limpiar |
| **Topología** | El mapa de la red: Internet, operador, las 5 sedes, sus enlaces coloreados según uso y, al hacer clic en una sede, sus segmentos y equipos | Clic en una sede para ver su detalle |
| **Tráfico** | Lo que ya existe en el panel del Sprint 3: uso de enlaces, demanda por clase y área, decisiones del controlador | Cambiar el clasificador (deshabilitado mientras corre un escenario) |
| **Evidencias** | Salida real de Open vSwitch y de Linux: switches y su controlador, reglas OpenFlow con `set_queue`, colas HTB con sus contadores | Botones de solo lectura que ejecutan comandos fijos y muestran el resultado |

La regla de oro: **después de un solo arranque antes de la presentación, nada requiere la terminal.**

### 1.1 Cómo lo hacen las herramientas reales (justificación)

- Las consolas de controladores SDN (la interfaz de ONOS, OpenDaylight) y las de redes administradas
  (Cisco Catalyst Center, Meraki) abren con un **mapa de topología** con enlaces coloreados por uso.
- Los centros de operación muestran **indicadores de calidad** (latencia, jitter, MOS) medidos con
  sondas activas, como IP SLA de Cisco. Nuestras sondas de voz, pagos y web cumplen ese papel.
- Los laboratorios de redes (Cisco Modeling Labs, EVE-NG, GNS3) se manejan desde una interfaz web
  que arranca y detiene la topología: el patrón es el mismo que el orquestador de la sección 5.1.
- **No** se dibujan los 276 equipos con todas sus conexiones: ninguna herramienta real lo hace,
  porque queda ilegible. Se muestra por niveles: operador → sedes → segmentos → equipos.

---

## 2. Guion de la demo (lo que debe funcionar)

Duración objetivo: 8 a 10 minutos. Todo con el mouse.

| Min | Acción en la consola | Qué ve el público |
|---|---|---|
| 0:00 | (Antes de entrar) El presentador ya ejecutó `demo/iniciar_demo.sh` y tiene abierto `http://127.0.0.1:8090` | — |
| 0:30 | Pestaña **Demo** → botón **Iniciar controlador** | El indicador "Controlador" pasa de gris a verde |
| 1:00 | Botón **Levantar red** (sin tráfico) | Barra de progreso; el contador sube hasta "44/44 switches conectados" |
| 2:00 | Pestaña **Topología** | Mapa de la red, todo en verde (sin tráfico). Clic en "Sala 1": sus 6 segmentos y 74 equipos |
| 3:00 | Pestaña **Evidencias** → **Switches y controlador**, **Reglas de la Sala 1**, **Colas de la Sala 1** | Salida real de OVS y de `tc`, con lo importante resaltado |
| 4:30 | Pestaña **Demo** → elegir `enlace_degradado` + `prioridad` + Sala 1 + "Rápido" → **Correr escenario** | La red se rearma; la línea de tiempo muestra las fases; cada fase al terminar muestra voz, pagos y web en verde o rojo |
| 5:00 | Mientras corre, pasar a **Topología** | El enlace de la Sala 1 se pone rojo en la fase "degradado" |
| 7:00 | Volver a **Demo** | Resultado: normal en verde, degradado en rojo (voz ~300 ms), recuperado en verde. Mensaje: "esto es lo que la IA debe resolver" |
| 8:00 | (Opcional) **Comparar** `respaldo_en_atencion`: `sin_qos` contra `prioridad` | Tabla lado a lado: la voz pasa de cientos de ms a ~11 ms |
| 9:00 | Cerrar con el dashboard de resultados y Azure DevOps (fuera de esta consola) | El pipeline en verde (pruebas, imagen, despliegue) y en Environments → laboratorio la versión que se acaba de usar en la demo |

---

## 3. Entorno

### 3.1 ¿Tiene que ser una máquina virtual?

No necesariamente, pero **sí necesita un Linux de verdad con permisos de administrador**. Mininet
usa *network namespaces* del kernel, Open vSwitch usa su módulo del kernel, y las colas usan
`tc` (HTB, netem, IFB). Por eso:

| Dónde | ¿Sirve? | Comentario |
|---|---|---|
| VM Ubuntu 22.04 en VirtualBox (la actual) | **Sí. Es la opción para la presentación** | Ya está probada con todo el proyecto |
| Laptop con Ubuntu instalado (nativo o dual boot) | Sí, y con mejor rendimiento | Mismos pasos de instalación que la VM |
| VM Ubuntu en Azure | Sí, en principio | Cumple literalmente "en Azure". Azure for Students da USD 100 de crédito sin tarjeta. Hay que verificar que el kernel de Azure traiga `openvswitch`, `sch_htb`, `sch_netem` e `ifb` (si falta alguno: `sudo apt install linux-modules-extra-azure`). La consola se abre por túnel SSH. **No improvisar esto la noche antes** |
| WSL2 en Windows | No recomendado | Su kernel no trae el módulo de Open vSwitch; habría que compilar un kernel propio |
| Docker Desktop (Windows/Mac) | No | Por dentro es otra VM y Mininet necesita privilegios y módulos del host |
| GitHub Codespaces, Azure Container Apps | No | No permiten módulos del kernel ni crear interfaces de red |

### 3.2 Requisitos en la máquina (ya instalados en la VM del proyecto)

- Ubuntu 22.04, 2 vCPU como mínimo (4 recomendado), 4 GB de RAM.
- Mininet 2.3, Open vSwitch con módulo del kernel, `iperf3`, `tc` (iproute2).
- Python 3.10 del sistema (lo usan Mininet, los escenarios y **el orquestador**).
- `.venv` con Python 3.9 y Ryu 4.34 (lo usa el controlador). Alternativa: el contenedor `docker compose`.
- Navegador en la misma máquina (o túnel SSH si es remota).

### 3.3 Puertos

| Puerto | Quién escucha | Notas |
|---|---|---|
| 6633 / 6653 | Ryu (OpenFlow) | Los switches de Mininet se conectan a `127.0.0.1:6633` |
| 8080 | Ryu (API REST y panel actual) | Solo `127.0.0.1` |
| **8090** | **Orquestador de demo (nuevo)** | Solo `127.0.0.1`. Sirve la consola y reenvía `/qos/*` a 8080 |

### 3.4 Lo que NO se toca

- La forma en que se **miden** las fases (`correr_fase`, sondas, goodput, telemetría). La demo solo
  agrega avisos de progreso; los números deben salir idénticos.
- `experimentos/resultados/escenarios.csv` y `comparacion.csv`: **las corridas de la demo no se
  mezclan con los datos de la tesis** (ver 5.2).
- Las colas, políticas y destinos en `politicas/*.yaml`.
- La API existente: `GET /qos/estado`, `PUT /qos/clasificador`, `GET /qos/telemetria`, `GET /qos/serie`,
  `GET /panel` (solo se agregan campos y rutas, nunca se quitan).
- Jira: no cambiar estados de las historias.

---

## 4. Arquitectura de la consola

```
                     Navegador (http://127.0.0.1:8090)
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │  Orquestador de demo  (demo/orquestador.py, root)    │
        │  · sirve la consola (demo/consola/index.html)        │
        │  · /demo/*  → acciones con lista blanca              │
        │  · /qos/*   → reenvío a Ryu (127.0.0.1:8080)         │
        └───────┬──────────────────────┬───────────────────────┘
   inicia/detiene│                     │ lanza y vigila
                 ▼                     ▼
   ┌──────────────────────┐   ┌──────────────────────────────────┐
   │ Ryu (qos_app.py)     │   │ Mininet + OVS                    │
   │ .venv como usuario,  │◄──┤  · empresa_xyz.py --esperar      │
   │ o docker compose     │   │    (red en reposo)               │
   │ API :8080            │   │  · escenario.py --progreso ...   │
   └─────────┬────────────┘   │    (escenario con tráfico)       │
             │                └───────────────┬──────────────────┘
             ▼                                ▼
   datos/telemetria.db              datos/progreso.json  datos/reloj.json
   topologia/inventario.csv         experimentos/resultados/demo.csv
   topologia/switches.csv
```

**Por qué un orquestador aparte y no dentro de Ryu:**

1. Mininet necesita `root`; el controlador no debe correr como `root` (y en Docker no puede).
2. Si la página la sirviera Ryu, el botón "Iniciar controlador" estaría en una página que no carga
   cuando el controlador está apagado.
3. `sudo mn -c` mata a cualquier proceso `ryu-manager` (Mininet lo trata como controlador). El
   orquestador sabe esto y vuelve a levantar Ryu después de limpiar.

---

## 5. Componentes a construir

### 5.1 Orquestador de demo — `demo/orquestador.py` (nuevo)

**Tecnología:** Python 3.10 del sistema, **solo librería estándar** (`http.server.ThreadingHTTPServer`,
`subprocess`, `threading`, `json`, `urllib.request`) + `yaml` (ya instalado). Sin Flask ni FastAPI:
así no hay nada que instalar con `sudo pip`.

**Arranque:** `sudo python3 demo/orquestador.py` (lo hace `demo/iniciar_demo.sh`). Escucha en
`127.0.0.1:8090`. Si no es root, termina con un mensaje claro.

**Configuración:** `demo/demo.yaml`

```yaml
controlador: lab               # lab | venv | docker (ver 5.1.1)
venv: .venv/bin/ryu-manager    # ruta relativa a la raíz del repo
datapath: kernel               # kernel | user (user solo para pruebas sin módulo de OVS)
resultados_demo: experimentos/resultados/demo.csv
escala_rapida: 0.5             # botón "Rápido": fases a la mitad
salas: [1, 2, 3, 4]
estrategias: [sin_qos, fila_corta, prioridad, estatica]
```

#### 5.1.1 Modelo de trabajos

- Hay **un solo trabajo pesado a la vez** (`red` o `escenario`). Las evidencias y los estados son
  livianos y siempre se pueden pedir.
- Cada trabajo es un subproceso lanzado con `subprocess.Popen([...], start_new_session=True)`,
  **nunca** con `shell=True`. La salida (stdout+stderr) va a un búfer circular de 500 líneas y a
  `datos/demo.log`.
- Estados de un trabajo: `inactivo` → `iniciando` → `corriendo` → `terminado` | `fallido` | `cancelado`.
- Cancelar = `SIGTERM` al grupo de procesos; si en 20 s no terminó, `SIGKILL` + `mn -c` + reiniciar
  Ryu si estaba encendido.
- Cómo se inicia y detiene el controlador según `demo.yaml:controlador`:
  - **`lab` (recomendado para la presentación):** el contenedor `qos-controlador-lab` que dejó el
    despliegue continuo del pipeline de Azure DevOps (`ci/desplegar.sh`). Iniciar:
    `["docker", "start", "qos-controlador-lab"]`; detener: `["docker", "stop", "qos-controlador-lab"]`.
    Así la demo usa **exactamente la versión que el pipeline probó y desplegó**, y se puede mostrar
    en Azure DevOps (Environments → laboratorio) qué versión es. Si el contenedor no existe:
    error "Todavía no hay un despliegue del pipeline: usa el modo venv o lanza el pipeline".
  - **`venv`:** Ryu del `.venv`, lanzado **como el usuario normal**, no como root:
    `["sudo", "-u", os.environ["SUDO_USER"], RYU, "controlador/qos_app.py"]` con `cwd` en la raíz del repo.
  - **`docker`:** `["docker", "compose", "up", "-d"]` / `["docker", "compose", "down"]`.
  - En los modos `lab` y `docker`, `sudo mn -c` **sí puede** apagar al controlador: `killall ryu-manager`
    como root alcanza también a los procesos de un contenedor. `restart: unless-stopped` suele
    revivirlo; tras limpiar, el orquestador espera unos segundos (`ESPERA_REINICIO_S`) y, si la API
    no vuelve, lo inicia de nuevo.
- Todo archivo que el orquestador o sus hijos creen como root en `datos/`, `topologia/` o
  `experimentos/resultados/` se devuelve al usuario (`os.chown` a `SUDO_UID`/`SUDO_GID`), igual
  que `devolver_al_usuario()` en `escenarios/escenario.py`.

#### 5.1.2 API del orquestador

Todas las respuestas son JSON (`Content-Type: application/json; charset=utf-8`). Errores:
`{"error": "<mensaje en español para mostrar al usuario>"}` con código 400, 409 o 500.

| Método y ruta | Cuerpo | Qué hace |
|---|---|---|
| `GET /` | — | Devuelve `demo/consola/index.html` |
| `GET /demo/estado` | — | Estado completo (ver ejemplo abajo). La consola lo pide cada 2 s |
| `POST /demo/controlador/iniciar` | — | Inicia Ryu. 409 si ya está corriendo |
| `POST /demo/controlador/detener` | — | Detiene Ryu. 409 si hay un trabajo pesado corriendo |
| `POST /demo/red/iniciar` | `{"estrategia": "colas"}` | Levanta la red en reposo (`empresa_xyz.py --sin-cli --esperar --estrategia colas`). 409 si hay otro trabajo o el controlador está apagado |
| `POST /demo/red/detener` | — | Apaga la red en reposo |
| `POST /demo/escenario` | `{"nombre": "enlace_degradado", "estrategias": ["prioridad"], "sala": 1, "rapido": true}` | Corre un escenario. Si la red en reposo está levantada, la apaga primero (el escenario arma su propia red). 1 estrategia = "Correr"; 2 = "Comparar" |
| `POST /demo/cancelar` | — | Cancela el trabajo pesado en curso |
| `POST /demo/limpiar` | — | `mn -c` y vuelve a iniciar Ryu si estaba encendido. Para cuando algo quedó colgado |
| `GET /demo/escenarios` | — | Lista de escenarios desde `escenarios/escenarios.yaml`: nombre, descripción corta, día y hora simulados, fases y su duración |
| `GET /demo/evidencia/<tipo>?sala=N` | — | Ejecuta un comando fijo de solo lectura (ver 5.1.3) y devuelve su salida |
| `GET /demo/log?desde=<n>` | — | Líneas del búfer desde la número `n` (para el visor de registro) |
| `GET,PUT /qos/*` | (igual que Ryu) | Reenvío transparente a `http://127.0.0.1:8080/qos/*`. Si Ryu no responde: 503 `{"error": "El controlador está apagado"}` |

**Validación (lista blanca):** `nombre` ∈ escenarios del YAML; cada estrategia ∈
`demo.yaml:estrategias`; `sala` ∈ `demo.yaml:salas`; `estrategias` con 1 o 2 elementos distintos;
`rapido` booleano. Cualquier otro campo o valor → 400. Ningún texto del usuario llega a un comando
sin pasar por esta validación.

**Ejemplo de `GET /demo/estado`:**

```json
{
  "controlador": {"estado": "corriendo", "modo": "venv", "pid": 4321, "api": true},
  "red": {"estado": "corriendo", "desde": 1793031000.5, "switches_esperados": 44},
  "trabajo": {
    "tipo": "escenario", "estado": "corriendo", "inicio": 1793031100.2,
    "parametros": {"nombre": "enlace_degradado", "estrategias": ["prioridad"], "sala": 1, "rapido": true},
    "lineas_log": 182
  },
  "ultimo_error": null
}
```

`controlador.api` = Ryu respondió a `GET /qos/estado` en menos de 1 s. `red.switches_esperados`
sale de contar las filas de `topologia/switches.csv` (44 en la topología actual).

#### 5.1.3 Evidencias (comandos fijos, solo lectura)

| `tipo` | Comando exacto (lista de argumentos) | Qué resaltar en la consola |
|---|---|---|
| `switches` | `["ovs-vsctl", "show"]` recortado a los bridges `acc0..acc4` + `["ovs-vsctl", "--columns=name,is_connected", "list", "Controller"]` | `is_connected: true` y el número de bridges |
| `reglas` | `["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", f"acc{sala}"]` | Las acciones `set_queue:N` y las cookies `0x16` (por conexión) y `0x20` (por adelantado) |
| `colas` | `["tc", "-s", "class", "show", "dev", f"acc{sala}-eth2"]` (bajada) y lo mismo con `-eth1` (subida) | Una clase HTB por cola (`1:1` … `1:6`), con `Sent … bytes` y `dropped` |
| `qos` | `["ovs-vsctl", "list", "QoS"]` | `type: linux-htb` y las colas configuradas |

- `sala` validada contra `demo.yaml:salas` (o `0` para la oficina).
- Tiempo máximo por comando: 5 s. Salida máxima: 64 kB (se corta con aviso).
- Respuesta: `{"tipo": "reglas", "sala": 1, "comando": "ovs-ofctl -O OpenFlow13 dump-flows acc1",
  "salida": "...", "explicacion": "Cada línea es una regla OpenFlow. set_queue:N indica el carril…"}`.
- La `explicacion` es un texto fijo por tipo, en lenguaje simple (la escribe quien implementa).
- Si la red no está levantada: 409 `{"error": "Levanta la red primero"}`.

**Nota:** las interfaces de los switches de acceso se llaman `acc<N>-eth1` (hacia el operador =
subida) y `acc<N>-eth2` (hacia la sede = bajada), porque `EmpresaXYZ.acceso()` crea primero el
enlace al operador. Verificarlo una vez con `ip link | grep acc1` en la VM.

### 5.2 Cambios en `escenarios/escenario.py`

1. **Archivo de resultados aparte.** Nuevo argumento `--salida <ruta.csv>` (por defecto el actual
   `experimentos/resultados/escenarios.csv`). El contexto se guarda junto a ella con sufijo
   `_contexto.csv`. El orquestador siempre pasa `--salida experimentos/resultados/demo.csv`.
   Así las corridas de la presentación no ensucian los datos de la tesis.
2. **Progreso en vivo.** Nuevo argumento `--progreso <ruta.json>` (por defecto ninguno = no se
   escribe nada, para que las campañas sigan exactamente igual). Si se indica, `ejecutar()` escribe
   el archivo en estos momentos:
   - al empezar (todas las fases planificadas, en estado `pendiente`);
   - al empezar cada fase (`corriendo`, con hora simulada e inicio real);
   - al terminar cada fase (`terminada`, con sus métricas y si cumple);
   - al terminar todo (`terminado`) o si hay una excepción (`fallido`, con el mensaje).
   - **Escritura atómica:** escribir en `<ruta>.tmp` y luego `os.replace()`, para que nadie lea un
     JSON a medias. Devolver el archivo al usuario con `devolver_al_usuario()`.
   - Implementarlo como una clase pequeña `Progreso` en un módulo nuevo `escenarios/progreso.py`,
     que `ejecutar()` recibe como parámetro opcional (`progreso=None`). Sin `--progreso`, no se crea.

**Formato de `datos/progreso.json`:**

```json
{
  "version": 1,
  "estado": "corriendo",
  "actualizado": 1793031180.4,
  "parametros": {"escenarios": ["enlace_degradado"], "estrategias": ["prioridad"],
                 "sala": 1, "semilla": 7, "escala": 0.5},
  "objetivos": {"voz_lat95_ms": 150, "voz_mos": 4.0, "pagos_p95_ms": 500, "web_p95_ms": 3000},
  "corridas": [
    {
      "escenario": "enlace_degradado",
      "descripcion": "Sábado 21:30, sala concurrida. Se cae el enlace principal…",
      "estrategia": "prioridad",
      "fases": [
        {"nombre": "normal", "duracion_s": 15, "estado": "terminada",
         "hora_simulada": "sábado 21:30", "inicio_real": 1793031120.0, "fin_real": 1793031135.1,
         "enlace": null,
         "metricas": {"uso_bajada_pct": 36.2, "voz_lat95_ms": 11.3, "voz_mos": 4.4,
                      "pagos_p95_ms": 25.3, "web_p95_ms": 430.9, "video_lat95_ms": 6.5,
                      "respaldo_goodput_mbps": null},
         "cumple": {"voz": true, "pagos": true, "web": true},
         "valida": true},
        {"nombre": "degradado", "duracion_s": 30, "estado": "corriendo",
         "hora_simulada": "sábado 21:43", "inicio_real": 1793031150.3, "fin_real": null,
         "enlace": {"capacidad_pct": 30, "perdida_pct": 0.5}, "metricas": null, "cumple": null},
        {"nombre": "recuperado", "duracion_s": 15, "estado": "pendiente", "metricas": null}
      ]
    }
  ],
  "error": null
}
```

- Las métricas salen de la misma `fila` que ya arma `correr_fase()`; no se mide nada nuevo.
- `cumple.voz` = la `fila["cumple_voz"]` empieza con `"sí"`; `cumple.pagos` = `fila["cumple_pagos"] == "sí"`;
  `cumple.web` = `fila["cumple_web"]` empieza con `"sí"` (si la sonda web está apagada en ese
  escenario, `null`).
- `valida` = la columna `valida` de la fila (CPU menor a 90 %).
- Con 2 estrategias ("Comparar") hay dos elementos en `corridas`, en el orden en que corren.

### 5.3 Cambios en `topologia/empresa_xyz.py`

Nuevo argumento `--esperar`: después de `configurar()` y `resumen()`, **en lugar de abrir la CLI**,
espera hasta recibir `SIGTERM` o `SIGINT` y entonces limpia (`emp.limpiar()`, `emp.net.stop()`) como
hace hoy el bloque `finally`. Imprime `*** Red lista` cuando termina de configurar (el orquestador
lo usa para saber que la red está arriba). Se usa con `--sin-cli`.

### 5.4 Cambios en el controlador (`controlador/qos_app.py` y `controlador/telemetria.py`)

1. `estado()` agrega `"switches_conectados": [<nombres de TODOS los switches conectados>]` y
   `"total_switches": <filas de switches.csv>`. (Hoy solo lista los de acceso.)
2. Nueva ruta **`GET /qos/topologia`**. Arma la estructura desde `topologia/inventario.csv`,
   `topologia/switches.csv` y los switches conectados. No mira tráfico (eso lo combina la consola
   con `/qos/serie` y `/qos/telemetria`). Formato:

```json
{
  "generado": 1793031200.1,
  "internet": [
    {"nombre": "inetvc", "ip": "203.0.113.10", "servicio": "videoconferencia"},
    {"nombre": "inetpago1", "ip": "203.0.113.60", "servicio": "pagos"}
  ],
  "sedes": [
    {
      "id": 1, "nombre": "Sala 1", "mbps": 30,
      "acceso": {"switch": "acc1", "dpid": 15, "conectado": true},
      "segmentos": [
        {"nombre": "maquinas", "switches": [
            {"nombre": "sw1maq", "conectado": true},
            {"nombre": "sw1is1", "conectado": true}],
         "equipos": 33,
         "areas": [{"area": "Máquinas", "equipos": 33,
                    "tipos": {"tragamonedas": 30, "servidor_sala": 1, "derby": 1, "ruleta": 1}}]},
        {"nombre": "cctv", "switches": [{"nombre": "sw1cct", "conectado": true}], "equipos": 25,
         "areas": [{"area": "Cámaras", "equipos": 25, "tipos": {"camara_ip": 24, "nvr": 1}}]}
      ]
    }
  ],
  "resumen": {"equipos": 276, "switches": 44, "conectados": 44}
}
```

   - Los conteos del ejemplo son los del inventario actual de la Sala 1; siempre se calculan del CSV.
   - Un switch de segmento pertenece a una sede por su `sede_id` en `switches.csv`; el segmento se
     deduce del inventario (los equipos de ese `sede_id` + `segmento`). Para las islas
     (`tipo: isla`) se agrupan dentro del segmento `maquinas` de su sede.
   - Si `inventario.csv` o `switches.csv` no existen (red nunca levantada): 200 con
     `{"sedes": [], "internet": [], "resumen": {...0}, "aviso": "Levanta la red una vez para generar el inventario"}`.
   - La lógica va en una función pura `armar_topologia(inventario, switches, conectados)` en
     `controlador/topologia.py` (nuevo), probada con pruebas unitarias. La ruta solo la llama.
   - Debe funcionar en Python 3.9 (el `.venv` de Ryu): nada de `match`, ni `X | Y` en tipos.
3. Nueva ruta **`GET /qos/progreso`**: devuelve el contenido de `datos/progreso.json` y de
   `datos/reloj.json` (`{"progreso": {...} | null, "reloj": {...} | null}`). Así la consola lo lee
   igual aunque Ryu corra en Docker (la carpeta `datos/` está montada).

### 5.5 Consola web — `demo/consola/index.html` (nuevo)

Parte del panel actual (`controlador/panel/index.html`) y lo amplía. **Un solo archivo HTML**, con
CSS y JavaScript dentro, **sin librerías externas ni CDN** (debe funcionar sin Internet). Mismos
colores por clase que el panel actual (`--tiempo_real`, `--critico`, etc.) y modo oscuro.
Interfaz en español. Ancho mínimo cómodo: 1280 px (proyector); debe verse bien también a 1920 px.

#### 5.5.1 Estructura general

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Empresa XYZ · QoS adaptativa      ● Controlador  ● Red 44/44  ● Escenario    │
│ [ Demo ] [ Topología ] [ Tráfico ] [ Evidencias ]                            │
├──────────────────────────────────────────────────────────────────────────────┤
│                         (contenido de la pestaña)                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

- Encabezado fijo con tres indicadores de estado (gris = apagado, ámbar = iniciando, verde = ok,
  rojo = error) que se actualizan con `GET /demo/estado` cada 2 s.
- Si el orquestador no responde: banda roja "La consola perdió contacto con el orquestador" y
  todos los botones deshabilitados.
- Las pestañas se recuerdan en `location.hash` (`#demo`, `#topologia`, `#trafico`, `#evidencias`).

#### 5.5.2 Pestaña Demo

```
┌─ Entorno ─────────────────────────┐  ┌─ Escenario ─────────────────────────────┐
│ Controlador  ● corriendo          │  │ Escenario  [ enlace_degradado      ▾ ]   │
│ [Iniciar] [Detener]               │  │ "Sábado 21:30, se cae el enlace…"       │
│                                   │  │ Sala       [ 1 ▾ ]   Velocidad (•) Rápido│
│ Red          ● 44/44 switches     │  │ Estrategia [ prioridad ▾ ]              │
│ [Levantar red] [Apagar red]       │  │ [ Correr escenario ]                     │
│                                   │  │ Comparar con [ sin_qos ▾ ] [ Comparar ]  │
│ [Limpiar todo]  (con confirmación)│  │ [ Cancelar ]                             │
└───────────────────────────────────┘  └──────────────────────────────────────────┘
┌─ Escenario en curso: enlace_degradado · prioridad · Sala 1 ─────────────────────┐
│  sábado 21:43 (simulado) · franja: atención                                      │
│  ██████████ normal ✓ │ ███████░░░░░░░░░░ degradado (corriendo) │ recuperado      │
│                                                                                  │
│  Fase        Voz p95     MOS   Pagos p95   Web p95    Enlace                     │
│  normal      11 ms ✓     4.4   25 ms ✓     431 ms ✓   100 %                      │
│  degradado   …midiendo                                30 %, 0,5 % pérdida        │
│  recuperado  pendiente                                                           │
│  Objetivos: voz ≤ 150 ms y MOS ≥ 4,0 · pagos ≤ 500 ms · web ≤ 3000 ms            │
└──────────────────────────────────────────────────────────────────────────────────┘
[ Ver registro ▸ ]   (desplegable con las últimas líneas de /demo/log, letra monoespaciada)
```

Comportamiento:

- Los botones se habilitan según el estado: "Levantar red" exige controlador corriendo y ningún
  trabajo; "Correr" y "Comparar" exigen controlador corriendo; "Detener controlador" se deshabilita
  con un trabajo corriendo; "Cancelar" solo con un trabajo corriendo.
- Cada botón muestra un estado de "trabajando…" mientras espera la respuesta, y un aviso breve con
  el resultado o el `error` del servidor.
- "Limpiar todo" pide confirmación **dentro de la página** (no `confirm()` del navegador).
- La lista de escenarios viene de `GET /demo/escenarios`; al elegir uno se muestra su descripción y
  su duración estimada (suma de fases × escala + ~60 s de armado de la red).
- La línea de tiempo y la tabla salen de `GET /qos/progreso` cada 2 s mientras haya un escenario.
  Un valor fuera de objetivo se pinta en rojo con "✗"; dentro, en verde con "✓". El rojo nunca es
  el único indicador (también el símbolo).
- En "Comparar", dos tablas lado a lado (una por estrategia) con las mismas filas.
- Al terminar: mensaje "Escenario terminado. Resultados guardados en experimentos/resultados/demo.csv".
- **Avisos que se muestran al usuario** (texto exacto sugerido):
  - Controlador apagado al pulsar "Correr": "Primero inicia el controlador."
  - Escenario con la red en reposo levantada: "La red en reposo se apagará: el escenario arma la suya."
  - Error del escenario: el `error` de `progreso.json` + "Usa «Limpiar todo» y vuelve a intentar."

#### 5.5.3 Pestaña Topología

Diagrama SVG dibujado por la propia página (sin librerías) a partir de `GET /qos/topologia`,
`GET /qos/serie?minutos=2` y `GET /qos/telemetria?minutos=2`, refrescado cada 5 s.

```
  INTERNET                   OPERADOR                      SEDES
 ┌────────────┐                                     ┌──────────────────────┐
 │ Teams/Zoom │╲                                ════│ Oficina   50 Mbps    │ 30 equipos
 │ SIP        │ ╲                              ╱    │ ▓▓▓░░ 38 %  ↓ ↑      │
 │ IA         │  ╲   ┌────────────────────┐   ╱     └──────────────────────┘
 │ YouTube    │───── │ Operador (rop)     │───────  Sala 1 30 Mbps ▓▓▓▓▓ 92 %  (rojo)
 │ Descargas  │  ╱   │ Internet + MPLS    │   ╲     Sala 2 20 Mbps ▓░░░░ 10 %
 │ Web        │ ╱    └────────────────────┘    ╲    Sala 3 …
 │ Pagos A/B  │╱                                ╲   Sala 4 …
 └────────────┘
```

- Columna izquierda: los servicios de Internet (de `internet[]`), agrupados por servicio.
- Centro: el operador.
- Derecha: las 5 sedes, una tarjeta cada una, unidas al operador por una línea cuyo **grosor** es
  la capacidad del enlace y cuyo **color** es el uso del último dato de `/qos/serie` (el mayor
  entre subida y bajada): verde < 70 %, ámbar 70–90 %, rojo ≥ 90 %. Al lado, el porcentaje y los Mbps.
- Si en `progreso.json` la fase actual tiene `enlace.capacidad_pct < 100` para esa sala, la línea
  se dibuja **punteada** con la etiqueta "enlace degradado: 30 %".
- Switch desconectado → su tarjeta con borde gris punteado y la etiqueta "sin controlador".
- **Clic en una sede** → se abre debajo un panel de detalle:

```
 Sala 1 · switch de acceso acc1 (conectado) · 74 equipos
 ┌ maquinas ────────┐ ┌ pagos ────┐ ┌ cctv ─────────┐ ┌ administracion ┐ ┌ wifi_clientes ┐ ┌ wifi_personal ┐
 │ sw1maq + 3 islas │ │ sw1pag    │ │ sw1cct        │ │ sw1adm         │ │ sw1wfc        │ │ sw1wfp        │
 │ 33 equipos       │ │ 2 equipos │ │ 25 equipos    │ │ 6 equipos      │ │ 6 equipos     │ │ 2 equipos     │
 │ ■ crítico 1,2 Mb │ │ ■ crítico │ │ ■ vigilancia  │ │ ■ tiempo real… │ │ ■ restringido │ │ ■ masivo      │
 └──────────────────┘ └───────────┘ └───────────────┘ └────────────────┘ └───────────────┘ └───────────────┘
```

  - Cada segmento muestra sus switches, cuántos equipos tiene y, desde `/qos/telemetria`
    (`areas[]` de esa sede), las clases de tráfico que está usando ahora con sus Mbps (cuadrito del
    color de la clase). Sin tráfico: "sin tráfico".
  - Al pasar el mouse sobre un segmento: lista de áreas y tipos de equipo (de `areas[]` de
    `/qos/topologia`).
- Leyenda fija abajo: colores de uso del enlace y colores de las clases.
- El dibujo debe ser determinista (mismas posiciones siempre) y entrar sin barra horizontal en 1280 px.

#### 5.5.4 Pestaña Tráfico

Es el panel actual del Sprint 3 (tarjetas por sede, demanda por área, decisiones). Se mueve tal cual
a esta pestaña. Único cambio: los botones del clasificador se deshabilitan mientras corre un
escenario, con el texto "El escenario controla el clasificador".

#### 5.5.5 Pestaña Evidencias

```
 Sala [ 1 ▾ ]
 [ Switches y controlador ]  [ Reglas OpenFlow ]  [ Colas HTB ]  [ Configuración QoS ]

 ┌ ovs-ofctl -O OpenFlow13 dump-flows acc1 ─────────────────────────────── [Copiar] ┐
 │ Cada línea es una regla. «set_queue:N» manda la conexión al carril N…            │
 │ cookie=0x20, priority=8, ip,nw_dst=203.0.113.10 actions=set_queue:1,output:1…    │
 │ …                                                                                │
 └──────────────────────────────────────────────────────────────────────────────────┘
```

- Texto monoespaciado, con resaltado (fondo suave) de: `set_queue:\d+`, `cookie=0x16`,
  `cookie=0x20`, `is_connected: true`, `class htb 1:\d+`, `dropped \d+`.
- La línea de explicación es un texto fijo por tipo, en lenguaje simple.
- Botón "Copiar" con `navigator.clipboard.writeText` y alternativa de seleccionar el texto.

### 5.6 Arranque — `demo/iniciar_demo.sh` y acceso directo

```bash
#!/usr/bin/env bash
# Inicia el orquestador (pide la contraseña de sudo una vez) y abre la consola.
cd "$(dirname "$0")/.."
sudo -v || exit 1
sudo nohup python3 demo/orquestador.py > datos/orquestador.log 2>&1 &
for i in $(seq 1 20); do curl -sf http://127.0.0.1:8090/demo/estado >/dev/null && break; sleep 0.5; done
xdg-open http://127.0.0.1:8090 >/dev/null 2>&1 &
```

Más un acceso directo `demo/QoS-Demo.desktop` (Terminal=true para poder escribir la contraseña de
sudo) que el usuario copia a su escritorio. **Este es el único paso con terminal y se hace antes de
la presentación.**

### 5.7 Lo que queda fuera de alcance

- Bytes por cola en vivo dentro de la consola (OpenFlow *queue stats*). Queda para después: no se
  puede probar fuera de la VM con colas HTB reales.
- Autenticación de usuarios en la consola (solo escucha en `127.0.0.1`).
- Desplegar en Azure. Esta consola corre donde corre Mininet.
- La IA (Sprints 4 y 5): la consola solo deja espacio para una estrategia `ia` futura en la lista.

---

## 6. Pruebas

### 6.1 Pruebas unitarias nuevas (deben correr sin root y sin Mininet)

| Archivo | Qué prueba |
|---|---|
| `controlador/test_topologia.py` | `armar_topologia()` con un inventario y switches pequeños: sedes ordenadas, conteo de equipos por segmento, islas dentro de `maquinas`, `conectado` según la lista, archivos inexistentes → estructura vacía con aviso |
| `escenarios/test_progreso.py` | `Progreso`: escritura atómica (no queda `.tmp`), transiciones pendiente → corriendo → terminada, cálculo de `cumple`, `fallido` con mensaje, sin `--progreso` no se crea archivo |
| `demo/test_orquestador.py` | Validación de la lista blanca (escenario inexistente, estrategia rara, sala 9, 3 estrategias, campos de más → error), armado de los comandos de cada acción **sin ejecutarlos** (inyectar un ejecutor falso), reglas de estados (no se puede levantar la red con un escenario corriendo, etc.), reenvío `/qos/*` con un servidor falso |
| `escenarios/test_escenarios.py` | `--salida` escribe en otro CSV y no toca `escenarios.csv` |

Todas deben pasar con `python3 -m unittest discover -p "test_*.py"` y con el pipeline
(`ci/pruebas_junit.py`). `pyflakes` sin avisos. Hoy hay 155 pruebas: el total debe subir, nunca bajar.

### 6.2 Prueba manual en la VM (lista de verificación)

1. `demo/iniciar_demo.sh` abre la consola; los tres indicadores en gris.
2. Iniciar controlador → verde en menos de 10 s.
3. Levantar red → "44/44" en menos de 90 s. Topología muestra las 5 sedes en verde.
4. Clic en Sala 1 → 6 segmentos, 74 equipos en total.
5. Evidencias → las cuatro funcionan; en Reglas aparecen líneas con `cookie=0x20` y `set_queue`.
6. Correr `enlace_degradado` + `prioridad` + Sala 1 + Rápido → la red en reposo se apaga sola, el
   escenario arranca, la tabla se llena fase por fase; en la fase degradado la Sala 1 se ve
   punteada/roja en Topología; termina en menos de 4 minutos.
7. `experimentos/resultados/demo.csv` tiene las filas nuevas y `escenarios.csv` **no cambió**
   (`git status` limpio para ese archivo).
8. Comparar `respaldo_en_atencion`: `sin_qos` contra `prioridad` → dos tablas, voz claramente peor en `sin_qos`.
9. Cancelar a mitad de un escenario → estado "cancelado" en menos de 30 s y se puede correr otro.
10. Limpiar todo → Ryu vuelve a estar verde.
11. Cerrar y volver a abrir el navegador → la consola recupera el estado actual.
12. Todo lo anterior **sin abrir otra terminal**.

---

## 7. Criterios de aceptación

- [ ] El guion de la sección 2 se completa de principio a fin solo con el mouse.
- [ ] Ningún botón ejecuta un comando armado con texto libre: todo pasa por la lista blanca.
- [ ] El orquestador y la API de Ryu solo escuchan en `127.0.0.1`.
- [ ] Las corridas de la demo van a `demo.csv`; los CSV de la tesis no cambian.
- [ ] Sin `--progreso`, `escenario.py` y `campana.py` se comportan exactamente como antes.
- [ ] La consola funciona sin Internet (sin CDN, sin fuentes externas).
- [ ] Pruebas unitarias nuevas pasan; total de pruebas mayor a 155; `pyflakes` limpio.
- [ ] El panel antiguo en `http://127.0.0.1:8080/panel` sigue funcionando.
- [ ] La lista de verificación 6.2 pasa completa en la VM.

---

## 8. Trampas conocidas del proyecto (léelas antes de empezar)

| Trampa | Qué pasa | Qué hacer |
|---|---|---|
| `sudo mn -c` mata a `ryu-manager` (también el de un contenedor) | El controlador se apaga sin aviso, en cualquier modo | Después de limpiar, el orquestador comprueba la API y reinicia el controlador si estaba encendido y no volvió |
| Ryu necesita Python 3.9 (`.venv`); Mininet usa 3.10 del sistema | `import ryu` falla con el Python equivocado | Código de `controlador/` compatible con 3.9; orquestador y escenarios con el 3.10 del sistema |
| Archivos creados por `sudo` quedan de root | Luego el análisis falla con `PermissionError` | `chown` a `SUDO_UID:SUDO_GID` (ya existe `devolver_al_usuario()`) |
| `tc qdisc replace … netem` conserva el `rate` anterior | El enlace queda limitado después de la fase degradada | Ya está resuelto en `escenarios/operador.py`; no reimplementarlo |
| Contadores de OVS "no disponible" (2^64 − 1) | Aparecen billones de Mbps | Ya está resuelto en `telemetria.py`; si la consola calcula algo, ignorar valores mayores a 10 veces la capacidad |
| Pausas de la VM | Una fase con cortes y números absurdos | La fila trae `valida`/`cpu_pct`; la consola muestra "fase no válida (CPU alta)" si `valida` es falso |
| Puerto 6633 u 8080 ocupado (Ryu viejo, `docker compose` o el contenedor `qos-controlador-lab` del CD) | El controlador no inicia | El orquestador revisa el puerto antes y muestra qué lo ocupa; en modo `venv`, ofrece detener `qos-controlador-lab` |
| El pipeline despliega en medio de la demo | Cambia el controlador mientras se presenta | `ci/desplegar.sh` no despliega si hay Mininet corriendo; además, no subir a `main` el día de la presentación o desmarcar *Desplegar al laboratorio* |
| Un escenario arma su propia red | Choca con la red en reposo | El orquestador apaga la red en reposo antes de lanzar el escenario |
| Primera corrida en una VM nueva | `inventario.csv` no existe y la topología sale vacía | Mostrar el aviso de la API y pedir "Levantar red" una vez |

---

## 9. Estructura de archivos resultante

```
demo/
  orquestador.py          (nuevo) servidor HTTP, trabajos, lista blanca, evidencias, reenvío /qos/*
  demo.yaml               (nuevo) configuración
  iniciar_demo.sh         (nuevo) arranque en un paso
  QoS-Demo.desktop        (nuevo) acceso directo
  consola/index.html      (nuevo) la consola (4 pestañas)
  test_orquestador.py     (nuevo)
controlador/
  topologia.py            (nuevo) armar_topologia()
  test_topologia.py       (nuevo)
  qos_app.py              (cambia) estado() + /qos/topologia + /qos/progreso
escenarios/
  progreso.py             (nuevo) clase Progreso
  test_progreso.py        (nuevo)
  escenario.py            (cambia) --salida, --progreso
  test_escenarios.py      (cambia) prueba de --salida
topologia/
  empresa_xyz.py          (cambia) --esperar
.gitignore                (cambia) datos/progreso.json, datos/demo.log, datos/orquestador.log,
                                   experimentos/resultados/demo*.csv
docs/ESPECIFICACION_DEMO.md   este documento
```

---

## 10. Estilo de código del proyecto

- Nombres, comentarios, mensajes y textos de la interfaz **en español** (como el resto del repo).
- Solo librería estándar salvo `yaml`. Nada que requiera `sudo pip install`.
- Funciones puras para la lógica (fáciles de probar) y capas finas para HTTP y subprocesos.
- Docstrings cortos que digan **para qué** sirve algo, no cómo.
- Mensajes de error que digan qué pasó y qué hacer.
- Sin `shell=True`. Sin `eval`. Sin rutas armadas con texto del usuario.

---

## 11. Seguridad (resumen)

- Orquestador y Ryu solo en `127.0.0.1`. Para usarlo desde otra máquina: túnel SSH
  (`ssh -L 8090:127.0.0.1:8090 usuario@vm`), nunca abrir el puerto.
- El orquestador corre como root porque Mininet lo exige: por eso **solo** ejecuta las acciones de
  la lista blanca, con argumentos validados, y no tiene ninguna ruta que acepte un comando.
- Ryu sigue corriendo como usuario normal.

---

## 12. Plan de trabajo (en este orden)

| Paso | Qué | Prioridad | Estimado |
|---|---|---|---|
| 1 | `escenarios/progreso.py` + `--progreso` + `--salida` en `escenario.py` + pruebas | P0 | 1,5 h |
| 2 | `--esperar` en `empresa_xyz.py` | P0 | 0,5 h |
| 3 | `demo/orquestador.py` con controlador, red, escenario, cancelar, limpiar, estado, log, reenvío `/qos/*` + pruebas | P0 | 3 h |
| 4 | Consola: encabezado + pestaña Demo (botones, línea de tiempo, tabla de fases) | P0 | 2,5 h |
| 5 | `controlador/topologia.py` + `/qos/topologia` + `switches_conectados` + `/qos/progreso` + pruebas | P1 | 1,5 h |
| 6 | Consola: pestaña Topología | P1 | 3 h |
| 7 | Evidencias en el orquestador + pestaña Evidencias | P1 | 1,5 h |
| 8 | Mover el panel actual a la pestaña Tráfico | P2 | 0,5 h |
| 9 | `iniciar_demo.sh`, acceso directo, `.gitignore` | P0 | 0,5 h |
| 10 | Lista de verificación 6.2 en la VM y ajustes | P0 | 1,5 h |

Total aproximado: 16 horas. **Si no alcanza el tiempo**, el mínimo útil es P0 (pasos 1–4, 9, 10):
botones para controlador, red y escenarios, con la tabla de fases en vivo. La topología (P1) es lo
siguiente en importancia.

Sugerencia de entrega: una rama `demo-consola`, un commit por paso, y fusionar a `main` solo
después de pasar la lista 6.2.

---

## 13. Instrucción sugerida para la IA que implemente

> Estás trabajando en el repositorio `qos-adaptativa` (Python, Mininet, Open vSwitch, Ryu). Lee
> completo `docs/ESPECIFICACION_DEMO.md` y los archivos que menciona antes de escribir código.
> Implementa **solo el paso N** de la sección 12. Respeta la sección 3.4 (lo que no se toca), la 8
> (trampas) y la 10 (estilo). Usa solo la librería estándar y `yaml`. Escribe las pruebas de la
> sección 6.1 que correspondan a este paso y córrelas con
> `python3 -m unittest discover -p "test_*.py"`; también `python3 -m pyflakes` sobre los archivos
> que cambies. Al terminar, muestra un resumen de los archivos cambiados y cualquier punto donde
> el código real no coincida con la especificación. No hagas commit.

---

## 14. Referencias en el repositorio

| Para entender… | Mira |
|---|---|
| Cómo corre un escenario y qué mide cada fase | `escenarios/escenario.py` (`ejecutar`, `correr_fase`, `imprimir`) |
| Los escenarios disponibles, sus fases y objetivos | `escenarios/escenarios.yaml` |
| El reloj simulado y `datos/reloj.json` | `escenarios/reloj.py` |
| Cómo se arma la red y cómo se llaman las interfaces | `topologia/empresa_xyz.py` (`acceso`, `guardar_switches`, `configurar`) |
| La API actual y el panel | `controlador/qos_app.py` (clase `QoSRest`), `controlador/panel/index.html` |
| Los datos que ya entrega la telemetría | `controlador/telemetria.py` (`datos_panel`, `serie_enlaces`) |
| Clases, colas y colores | `politicas/politicas.yaml` |
| Cómo se ejecutan las pruebas en CI | `ci/pruebas_junit.py`, `azure-pipelines.yml` |
