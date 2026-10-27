# Desarrollo local de la consola de demo

## Estado de esta base

La rama `demo-consola` parte del commit `8678245` e incorpora el paquete adjunto
`sprint3-azure-cicd.zip`: panel del controlador, telemetría actualizada, Docker,
scripts de CI/CD y la especificación. La consola nueva todavía está pendiente.
Este commit no instala herramientas del sistema ni despliega el controlador.

La especificación funcional está en [ESPECIFICACION_DEMO.md](ESPECIFICACION_DEMO.md).

## Abrir en Visual Studio Code

Abre la carpeta raíz `qos-adaptativa` con Archivo → Abrir carpeta. En Control de
código fuente, comprueba que la rama activa sea `demo-consola`. Si el comando
`code` está disponible, también puedes usar `code .` desde esa carpeta.

Usa la extensión Python de Microsoft y selecciona el intérprete adecuado:

- Python 3.10 del sistema para escenarios, topología y el futuro orquestador.
- Python 3.9 en `.venv` para Ryu; el controlador también puede correr en Docker.

No ejecutes el editor como administrador. Ejecuta con privilegios únicamente
los procesos de red que lo necesiten. No uses `sudo pip`.

## Verificar antes de implementar

Desde la raíz del proyecto:

```bash
python3 -m unittest discover -p 'test_*.py'
python3 escenarios/escenario.py --listar
python3 escenarios/escenario.py --nombre enlace_degradado --plan
git status --short
```

Algunas pruebas abren conexiones locales; un entorno restringido puede impedirlo.
Una prueba omitida no acredita el comportamiento de la red real.

La prueba completa requiere Ubuntu con Mininet, Open vSwitch, iperf3, tc y los
módulos del kernel indicados en la especificación, más Ryu en Python 3.9 o Docker.
En el entorno utilizado para preparar esta base esas herramientas no estaban
disponibles en PATH y el acceso administrativo estaba restringido. Es necesario
verificarlas en la terminal de tu Ubuntu antes de probar escenarios reales.

Para revisar estilo, instala `pyflakes` en un entorno virtual de desarrollo y
ejecuta allí:

```bash
python -m pyflakes controlador escenarios trafico experimentos politicas topologia ci
```

Los detalles de CI/CD están en [../ci/README.md](../ci/README.md). Configurar o
ejecutar un pipeline con despliegue puede cambiar el controlador del laboratorio;
no hace falta hacerlo para comenzar a desarrollar la consola.

## Orden de trabajo recomendado

1. Añadir `escenarios/progreso.py`, `--progreso` y `--salida`, con pruebas sin
   Mininet. Conservar las mediciones actuales y separar los CSV de la demo.
2. Añadir `--esperar` a la topología y comprobar la limpieza al detenerla.
3. Crear el orquestador con validación de entradas y un ejecutor falso para
   probar estados y comandos sin privilegios.
4. Crear la pestaña Demo y conectar los botones con las acciones ya probadas.
5. Añadir API de topología, mapa y evidencias; reutilizar el panel en Tráfico.
6. Probar todo el guion en la VM con red real antes de considerar terminada la demo.

Haz un commit por paso, con sus pruebas. No cambies políticas, mediciones ni
resultados históricos de la tesis para conseguir que la presentación salga verde.
No presentes cifras de ejemplo como resultados medidos.

## Guardar avances

Revisa el diff antes de agregar los archivos que cambiaste:

```bash
git diff
git status --short
```

Luego selecciona esos archivos en Control de código fuente y crea el commit.
Un commit guarda el avance local; publicar o sincronizar envía cambios a GitHub.
Esta base se prepara localmente, sin publicar cambios.
