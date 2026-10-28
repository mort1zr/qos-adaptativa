# Validación real del laboratorio

La demo se verificó el 26 de octubre de 2026 en Ubuntu 22.04, kernel
6.8.0-138-generic, con 3 CPU virtuales y aproximadamente 4 GB de RAM.
El controlador Ryu corrió en `qos-controlador:local` mediante Docker; Mininet,
Open vSwitch y las colas HTB corrieron en el host. La consola usó modo `docker`.

## Comprobaciones completadas

- Red en reposo con 44 de 44 switches conectados al controlador.
- Inventario de 276 equipos: 268 en sedes y 8 servidores que representan Internet.
- Cinco sedes; Sala 1 con seis segmentos y 74 equipos.
- Cuatro consultas de evidencias funcionales: switches, reglas, colas y QoS.
- Reglas anticipadas con cookie `0x20` y `set_queue`; en Sala 1 se observaron 346.
- Colas HTB reales en ambos sentidos del acceso y QoS `linux-htb`.
- Transición desde red en reposo a escenario, ejecución y limpieza al terminar.
- Progreso, reloj simulado, telemetría y comparación visibles en el navegador.
- Cambio manual de clasificador bloqueado durante el escenario.
- Recuperación de progreso y opciones al recargar el navegador.
- Resultados de demo separados: `demo.csv` y `demo_contexto.csv`.
- Los 17 archivos rastreados de políticas y resultados históricos comprobados
  mantuvieron exactamente sus hashes después de las corridas.
- 187 pruebas ejecutadas: 186 correctas, una omitida; pyflakes sin avisos.

## Comparación principal

Escenario `respaldo_en_atencion`, Sala 1, semilla 7, ruido 0, escala 1.
Cada estrategia ejecutó fases de 30, 60 y 30 segundos. Las seis fases resultaron
válidas según el criterio de CPU del proyecto.

Resultados de la fase `respaldo`:

| Métrica | sin_qos | prioridad | Objetivo |
|---|---:|---:|---:|
| Voz, latencia p95 | 394,24 ms | 13,97 ms | ≤ 150 ms |
| MOS estimado de voz | 3,07 | 4,40 | ≥ 4 |
| Pagos, respuesta p95 | 850,3 ms | 29,2 ms | ≤ 500 ms |
| Web, carga p95 | 5778,8 ms | 1051,8 ms | ≤ 3000 ms |
| Goodput del respaldo | 18,43 Mbps | 20,89 Mbps | Sin objetivo de aceptación |
| CPU del host | 61,2 % | 47,6 % | Menor que 90 % para validar la fase |

Son resultados de una corrida comparativa del laboratorio, no una conclusión
estadística de campañas repetidas. La carga web, pagos y voz son generados por
los programas de prueba del proyecto; no son sesiones de aplicaciones comerciales.
La estrategia prioridad combina clasificación por destino, reglas OpenFlow y
colas por clase con filas cortas. Esta comparación no aísla por separado el
beneficio de cada mecanismo.

## Enlace degradado

También se ejecutó `enlace_degradado` con prioridad y escala 0,5. La voz pasó de
12,17 ms en la fase normal a 307,61 ms con capacidad del operador reducida al
30 % y pérdida del 0,5 %. Ambas fases fueron válidas.

La recuperación produjo cifras dentro de los objetivos, pero la CPU fue del
92,7 %: esa fase quedó marcada inválida y no se utiliza como evidencia de
recuperación. La fila original se conserva, sin ajustar mediciones ni criterios.

## Ajustes de interfaz durante la validación

- El estado de red refleja los switches conectados durante escenarios.
- El mapa calcula el uso respecto de la capacidad disponible durante una
  degradación, muestra su porcentaje y descarta muestras anteriores a esa fase.
- Se restaura la selección de escenario al recargar y se evita mostrar el reloj
  de la corrida anterior durante la preparación de una nueva.
- Las fases inválidas conservan sus números pero no muestran marcas de cumplimiento.
- El detalle de sede indica que la demanda es una media de dos minutos y muestra
  más decimales para tráfico pequeño, como los pagos.

## Alcance pendiente

No se validó en esta sesión la cancelación de un escenario a mitad de fase con
el límite de 30 segundos ni todos los casos de recuperación tras fallos. Se
probó la cancelación de la red en reposo al sustituirla por el escenario.

El código de CI/CD está en la rama, pero no se verificó una ejecución en Azure
DevOps. La IA sigue pendiente. Estas pruebas no equivalen al cumplimiento de
toda la lista manual de aceptación de la especificación.
