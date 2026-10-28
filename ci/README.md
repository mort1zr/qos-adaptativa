# CI/CD con Azure DevOps

Cada vez que se sube un cambio a `main` (o se abre un pull request), Azure DevOps corre
el pipeline `azure-pipelines.yml`. Las tres primeras etapas son la **integración continua (CI)**:
comprueban que el cambio no rompe nada. La última es la **entrega continua (CD)**: pone la
versión aprobada en marcha en el laboratorio.

| Etapa | Qué hace | Dónde lo ves |
|---|---|---|
| **Calidad** | Las ~155 pruebas unitarias en Python 3.9 (la del Ryu) y 3.10 (la de Mininet), y un lint con `pyflakes` | Pestaña **Tests** del build |
| **Contenedor** | Construye la imagen del controlador (`Dockerfile`) y comprueba que arranque y responda la API y el panel | Registro del paso y artefacto `contenedor` |
| **Integración** (opcional) | Levanta la red de Mininet de verdad con ese contenedor y corre `prueba_destinos.py` (PCIII-20) | Artefacto `integracion` (CSV + registro de Ryu) |
| **Despliegue** (CD, solo `main`) | Pone esa imagen como el controlador del laboratorio (contenedor `qos-controlador-lab`), comprueba que responda y, si no, vuelve a la versión anterior. No se ejecuta en pull requests ni si hay un escenario corriendo | **Pipelines → Environments → laboratorio**: historial de versiones desplegadas. Artefacto `despliegue` |

## ¿Por qué un agente propio (la VM) y no los de Microsoft?

- El nivel gratuito de los agentes de Microsoft pide **vincular una suscripción de Azure**
  a la organización. El de los agentes propios (*self-hosted*) "se concede automáticamente":
  un trabajo a la vez, sin límite de minutos.
  Fuentes: [Configure and pay for parallel jobs](https://learn.microsoft.com/en-us/azure/devops/pipelines/licensing/concurrent-jobs?view=azure-devops),
  [Azure DevOps Services pricing](https://azure.microsoft.com/en-ca/pricing/details/devops/azure-devops-services/).
  Si al lanzarlo aparece *"No hosted parallelism has been purchased or granted"*, es que
  intentó usar un agente de Microsoft: revisa que el parámetro sea `agente = laboratorio`.
- Mininet y Open vSwitch necesitan el kernel de Linux y `sudo`: la prueba de integración
  **solo puede correr en una máquina así**. En empresas reales pasa lo mismo con las pruebas
  de red: se usan agentes propios en un laboratorio.

Si más adelante tienen una suscripción, al lanzar el pipeline se elige `agente = microsoft`
y las etapas de Calidad y Contenedor corren en la nube (las de Integración y Despliegue no:
necesitan la VM).

## Paso a paso (una sola vez, ~20 min)

### 1. Organización y proyecto
1. Entra a <https://dev.azure.com> con una cuenta de Microsoft (no pide tarjeta).
2. Crea una organización y dentro un proyecto privado, por ejemplo `qos-adaptativa`.

### 2. Grupo de agentes "Laboratorio"
1. En el proyecto: **Project settings → Agent pools → Add pool**.
2. Tipo **Self-hosted**, nombre **`Laboratorio`** (tiene que ser exactamente ese), marca
   *Grant access permission to all pipelines*.

### 3. Token para registrar el agente
1. Arriba a la derecha, **User settings → Personal access tokens → New Token**.
2. Alcance: **Agent Pools (Read & manage)**. Vencimiento: 30 días. Copia el token.

### 4. Instalar el agente en la VM
En **Agent pools → Laboratorio → New agent → Linux** aparece el enlace de descarga
del agente. En la VM, como tu usuario (no como root):

```bash
mkdir -p ~/azagent && cd ~/azagent
wget <enlace que muestra Azure DevOps>        # vsts-agent-linux-x64-<versión>.tar.gz
tar zxf vsts-agent-linux-x64-*.tar.gz
./config.sh       # URL: https://dev.azure.com/<tu-organización> · token del paso 3
                  # pool: Laboratorio · nombre del agente: vm-lab · lo demás con Enter
./run.sh          # deja esta terminal abierta: el agente queda "Online"
```

Para que corra solo al prender la VM: `sudo ./svc.sh install $USER && sudo ./svc.sh start`.

### 5. Permisos en la VM

```bash
sudo apt install -y python3.10-venv     # entornos aislados para las pruebas
sudo usermod -aG docker $USER           # para la etapa Contenedor (después: reiniciar sesión y el agente)
```

Solo si se va a usar la **Integración** (Mininet necesita `sudo`):

```bash
echo "$USER ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/qos-ci
```

> Esto le da al pipeline control total de la VM. Está bien para una VM de laboratorio
> dedicada; en una empresa se usa una máquina aislada solo para estas pruebas.

### 6. Crear el pipeline
1. **Pipelines → New pipeline → GitHub (YAML)**. Autoriza la app de Azure Pipelines
   solo para el repositorio `mort1zr/qos-adaptativa`.
2. **Existing Azure Pipelines YAML file → `/azure-pipelines.yml` → Run**.
3. La primera vez puede pedir *"This pipeline needs permission to access a resource"*:
   **View → Permit**.

### 7. Lanzarlo con la prueba de integración
**Run pipeline** → marca *Prueba de integración con Mininet* → **Run**. Antes, apaga tu Ryu del
`.venv` y `docker compose` si están corriendo (ocupan los puertos 6633 y 8080). El controlador
que dejó el despliegue (`qos-controlador-lab`) no hace falta apagarlo: la integración lo pausa y
lo vuelve a levantar sola.

### 8. (Opcional) Aprobación antes de desplegar
Después de la primera corrida aparece **Pipelines → Environments → laboratorio**. En
**⋯ → Approvals and checks → Approvals** puedes agregarte como aprobador: el pipeline se detiene
antes del despliegue hasta que alguien pulse **Approve**. Es como se protege un ambiente en una
empresa, y en la presentación se ve muy claro.

## Despliegue continuo (CD): qué cambia en tu forma de trabajar

- Después del primer despliegue, el controlador del laboratorio es el **contenedor**
  `qos-controlador-lab`, que arranca solo con la VM (`--restart unless-stopped`). Los
  escenarios y las campañas funcionan igual: se conectan a `127.0.0.1:6633`, y el panel sigue
  en `http://127.0.0.1:8080/panel`.
- Usa la carpeta del proyecto (`~/qos-adaptativa` por defecto, parámetro *Carpeta del proyecto*):
  lee de ahí `topologia/` y escribe la telemetría en `datos/`, donde la leen los escenarios.
- Las políticas (`politicas/*.yaml`) van **dentro de la imagen**: un cambio de política llega al
  laboratorio subiéndolo a `main`, que es justamente la idea de CD.
- Para volver a usar el Ryu del `.venv`: `docker stop qos-controlador-lab`
  (y `docker start qos-controlador-lab` para regresar).
- Si vas a dejar una campaña corriendo de noche, no subas cambios a `main` mientras tanto. Si
  igual se lanza el pipeline, el despliegue detecta la red de Mininet y **no** toca el
  controlador (la etapa falla con ese aviso y se puede volver a lanzar después).
- Para no desplegar en una corrida: **Run pipeline** → desmarca *Desplegar al laboratorio*.
- Ver qué versión corre: `docker inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' qos-controlador-lab`
  o el historial del ambiente en Azure DevOps.

## Correr lo mismo a mano en la VM

```bash
ci/preparar_python.sh python3.9 && "$(cat .ci-python)" ci/pruebas_junit.py   # pruebas + XML
ci/imagen.sh                                                                  # imagen + humo
IMAGEN=qos-controlador:ci ci/integracion.sh                                   # integración
IMAGEN=qos-controlador:ci VERSION=manual ci/desplegar.sh                      # despliegue
```

## El controlador en contenedor (sin pipeline)

```bash
mkdir -p datos
docker compose up -d --build
# luego, como siempre: sudo python3 escenarios/escenario.py ...  (se conecta a 127.0.0.1:6633)
# panel: http://127.0.0.1:8080/panel
docker compose down
```

Diferencia con el `.venv`: `sudo mn -c` ya no apaga al controlador.
