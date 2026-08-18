# Comparación estación (texto libre) vs urbanbike_operativa.estaciones

Generado comparando el campo `estacion` (texto libre) de las 11 bicicletas reales
de PocketBase contra los nombres de `urbanbike_operativa.estaciones` en ClickHouse
(9 estaciones reales migradas con `etl/05_migrar_estaciones.py`, más 2 filas de
prueba preexistentes que no se tocaron).

| Bicicleta | Estación (texto libre) | Resultado |
|---|---|---|
| UB-001 | Parque Central | Exacta |
| UB-002 | Parque El Ejido | Exacta |
| UB-003 | Malecon 2000 | Exacta |
| UB-004 | Malecon 2000 | Exacta |
| UB-005 | Parque central de Moraspungo | Exacta |
| UB-006 | Parque El Ejido | Exacta |
| UB-007 | Plaza Grande | Exacta |
| UB-008 | Parque El Ejido | Exacta |
| UB-009 | Parque El Ejido | Exacta |
| UB-010 | Parque El Ejido | Exacta |
| UB-011 | Parque La Carolina | Exacta |
