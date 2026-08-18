-- ============================================================
-- Informes simples S01 a S17 sobre urbanbike_operativa
-- Sintaxis verificada en ClickHouse 26.8
-- IMPORTANTE: el alias va ANTES de FINAL  ->  tabla AS x FINAL
-- ============================================================

-- S01. Movimientos de caja del dia. Objetivo OT 01.
SELECT fecha, tipo, concepto, monto
FROM (
    SELECT p.fecha AS fecha, 'Entrada' AS tipo, p.metodo AS concepto, p.monto AS monto
    FROM urbanbike_operativa.pagos AS p FINAL
    WHERE toDate(p.fecha) = today() AND p.estado = 'verificado'
    UNION ALL
    SELECT g.fecha, 'Salida', g.concepto, g.monto
    FROM urbanbike_operativa.gastos AS g
    WHERE toDate(g.fecha) = today()
)
ORDER BY fecha;

-- S01b. Resumen de ganancia del dia: entradas menos salidas.
SELECT
    round(sumIf(monto, tipo = 'Entrada'), 2) AS entradas,
    round(sumIf(monto, tipo = 'Salida'), 2)  AS salidas,
    round(sumIf(monto, tipo = 'Entrada') - sumIf(monto, tipo = 'Salida'), 2) AS ganancia
FROM (
    SELECT 'Entrada' AS tipo, p.monto AS monto
    FROM urbanbike_operativa.pagos AS p FINAL
    WHERE toDate(p.fecha) = today() AND p.estado = 'verificado'
    UNION ALL
    SELECT 'Salida', g.monto
    FROM urbanbike_operativa.gastos AS g
    WHERE toDate(g.fecha) = today()
);

-- S02. Tarifario vigente por bicicleta y modalidad. Objetivo OT 02.
SELECT b.codigo, mar.nombre AS marca, c.nombre AS categoria,
       t.modalidad, t.precio, t.minutos_gracia, t.recargo_minuto
FROM urbanbike_operativa.tarifas AS t FINAL
INNER JOIN urbanbike_operativa.bicicletas AS b FINAL ON b.id = t.id_bicicleta
INNER JOIN urbanbike_operativa.modelos_bicicleta AS m FINAL ON m.id = b.id_modelo
INNER JOIN urbanbike_operativa.marcas AS mar FINAL ON mar.id = m.id_marca
INNER JOIN urbanbike_operativa.categorias AS c FINAL ON c.id = m.id_categoria
WHERE t.estado = 'vigente' AND today() BETWEEN t.vigente_desde AND t.vigente_hasta
ORDER BY c.orden, b.codigo, t.modalidad;

-- S03. Promociones vigentes con su descuento. Objetivo OT 02.
SELECT pr.codigo, pr.nombre, pr.tipo_descuento, pr.valor,
       pr.aplica_a, pr.dias_semana, pr.fecha_inicio, pr.fecha_fin
FROM urbanbike_operativa.promociones AS pr FINAL
WHERE pr.estado = 'activa' AND today() BETWEEN pr.fecha_inicio AND pr.fecha_fin
ORDER BY pr.fecha_fin;

-- S04. Alquileres activos con garantia validada. Objetivo OT 03.
SELECT a.codigo AS alquiler,
       concat(u.nombre, ' ', u.apellido) AS ciclista,
       mp.marca_tarjeta, mp.ultimos4,
       g.monto_retenido, g.fondos_validados, g.estado
FROM urbanbike_operativa.alquileres AS a FINAL
INNER JOIN urbanbike_operativa.garantias AS g FINAL ON g.id_alquiler = a.id
INNER JOIN urbanbike_operativa.metodos_pago AS mp FINAL ON mp.id = g.id_metodo_pago
INNER JOIN urbanbike_operativa.usuarios AS u FINAL ON u.id = a.id_usuario
WHERE a.estado IN ('reservado', 'en_curso')
ORDER BY a.fecha_inicio;

-- S05. Bitacora de auditoria por rango de fechas. Objetivo OT 04.
SELECT a.fecha, a.usuario, a.modulo, a.accion, a.detalle
FROM urbanbike_operativa.auditoria AS a
WHERE toDate(a.fecha) BETWEEN {fecha_desde:Date} AND {fecha_hasta:Date}
ORDER BY a.fecha DESC;

-- S06. Facturas emitidas del dia. Objetivo OT 05.
SELECT f.serie, f.numero, f.fecha_emision,
       concat(u.nombre, ' ', u.apellido) AS cliente,
       f.subtotal, f.descuento, f.impuesto, f.total, f.estado
FROM urbanbike_operativa.facturas AS f FINAL
INNER JOIN urbanbike_operativa.usuarios AS u FINAL ON u.id = f.id_usuario
WHERE toDate(f.fecha_emision) = today()
ORDER BY f.numero;

-- S07. Pagos pendientes de verificacion. Objetivo OT 05.
SELECT p.fecha, concat(u.nombre, ' ', u.apellido) AS ciclista,
       p.metodo, p.monto, p.referencia, p.estado
FROM urbanbike_operativa.pagos AS p FINAL
INNER JOIN urbanbike_operativa.usuarios AS u FINAL ON u.id = p.id_usuario
WHERE p.estado = 'pendiente' AND p.metodo IN ('transferencia', 'efectivo')
ORDER BY p.fecha;

-- S08. Catalogo filtrado por categoria, marca y enfoque. Objetivo OT 06.
-- Nota: ClickHouse no admite subconsultas correlacionadas en la lista del SELECT,
-- por eso la foto principal se resuelve con un LEFT JOIN a una subconsulta agrupada.
SELECT b.codigo, mar.nombre AS marca, c.nombre AS categoria, m.nombre AS modelo,
       m.enfoque, m.marchas, m.tipo_frenos, m.suspension, m.rodado,
       m.es_electrica, b.estado, fp.foto
FROM urbanbike_operativa.bicicletas AS b FINAL
INNER JOIN urbanbike_operativa.modelos_bicicleta AS m FINAL ON m.id = b.id_modelo
INNER JOIN urbanbike_operativa.marcas AS mar FINAL ON mar.id = m.id_marca
INNER JOIN urbanbike_operativa.categorias AS c FINAL ON c.id = m.id_categoria
LEFT JOIN (
    SELECT id_bicicleta, any(url) AS foto
    FROM urbanbike_operativa.bicicleta_fotos FINAL
    WHERE es_principal = 1
    GROUP BY id_bicicleta
) AS fp ON fp.id_bicicleta = b.id
WHERE (c.nombre = {categoria:String} OR {categoria:String} = 'todas')
  AND (mar.nombre = {marca:String} OR {marca:String} = 'todas')
  AND (m.enfoque = {enfoque:String} OR {enfoque:String} = 'todos')
ORDER BY c.orden, mar.nombre, b.codigo;

-- S09. Inventario de bicicletas por estacion y estado. Objetivo OT 06.
SELECT e.nombre AS estacion, b.codigo, c.nombre AS categoria, b.estado, b.km_acumulados
FROM urbanbike_operativa.bicicletas AS b FINAL
INNER JOIN urbanbike_operativa.estaciones AS e FINAL ON e.id = b.id_estacion
INNER JOIN urbanbike_operativa.modelos_bicicleta AS m FINAL ON m.id = b.id_modelo
INNER JOIN urbanbike_operativa.categorias AS c FINAL ON c.id = m.id_categoria
ORDER BY e.nombre, b.codigo;

-- S10. Repuestos con existencias bajo el stock minimo. Objetivo OT 07.
SELECT r.codigo, r.nombre, r.categoria, r.stock_actual, r.stock_minimo,
       r.costo_unitario, r.proveedor,
       multiIf(r.stock_actual < r.stock_minimo / 2, 'critico', 'bajo') AS nivel
FROM urbanbike_operativa.repuestos AS r FINAL
WHERE r.activo = 1 AND r.stock_actual <= r.stock_minimo
ORDER BY r.stock_actual;

-- S11. Calendario de mantenimientos programados. Objetivo OT 08.
SELECT mp.fecha_programada, b.codigo AS bicicleta, c.nombre AS categoria,
       pl.nombre AS plan, mp.tipo, mp.estado
FROM urbanbike_operativa.mantenimientos_programados AS mp FINAL
INNER JOIN urbanbike_operativa.bicicletas AS b FINAL ON b.id = mp.id_bicicleta
INNER JOIN urbanbike_operativa.modelos_bicicleta AS m FINAL ON m.id = b.id_modelo
INNER JOIN urbanbike_operativa.categorias AS c FINAL ON c.id = m.id_categoria
INNER JOIN urbanbike_operativa.planes_mantenimiento AS pl FINAL ON pl.id = mp.id_plan
WHERE mp.estado = 'pendiente'
ORDER BY mp.fecha_programada;

-- S12. Devoluciones pendientes de inspeccion con avance del checklist. Objetivo OT 09.
SELECT a.codigo AS alquiler, b.codigo AS bicicleta, a.fecha_fin,
       i.items_revisados, i.items_totales,
       multiIf(i.items_revisados = i.items_totales, 'completa', 'incompleta') AS avance
FROM urbanbike_operativa.alquileres AS a FINAL
INNER JOIN urbanbike_operativa.bicicletas AS b FINAL ON b.id = a.id_bicicleta
LEFT JOIN urbanbike_operativa.inspecciones AS i FINAL ON i.id_alquiler = a.id
WHERE a.estado = 'devuelto' AND (i.estado != 'certificada' OR i.estado = '')
ORDER BY a.fecha_fin;

-- S13. Nomina de empleados activos por departamento. Objetivo OT 10.
SELECT u.codigo, concat(u.nombre, ' ', u.apellido) AS empleado, u.rol, u.email, u.estado
FROM urbanbike_operativa.usuarios AS u FINAL
WHERE u.rol != 'ciclista' AND u.estado = 'activo'
ORDER BY u.rol, u.apellido;

-- S14. Bicicletas reubicadas por rebalanceo. Objetivo OT 11.
SELECT a.fecha, a.usuario, a.detalle
FROM urbanbike_operativa.auditoria AS a
WHERE a.accion = 'rebalanceo'
ORDER BY a.fecha DESC;

-- S15. Ordenes abiertas por tecnico con su estado de reparacion. Objetivo OT 12.
SELECT o.codigo, b.codigo AS bicicleta,
       concat(u.nombre, ' ', u.apellido) AS tecnico,
       o.origen, o.tipo_falla, o.prioridad, o.estado_reparacion,
       o.fecha_apertura,
       dateDiff('day', o.fecha_apertura, now()) AS dias_abierta
FROM urbanbike_operativa.ordenes_mantenimiento AS o FINAL
INNER JOIN urbanbike_operativa.bicicletas AS b FINAL ON b.id = o.id_bicicleta
INNER JOIN urbanbike_operativa.usuarios AS u FINAL ON u.id = o.id_tecnico
WHERE o.estado_reparacion != 'cerrada'
ORDER BY o.prioridad, o.fecha_apertura;

-- S16. Viajes activos que superan el tiempo contratado. Objetivo OT 13.
SELECT a.codigo, concat(u.nombre, ' ', u.apellido) AS ciclista,
       b.codigo AS bicicleta, a.fecha_inicio, a.minutos_contratados,
       dateDiff('minute', a.fecha_inicio, now()) AS minutos_en_curso,
       dateDiff('minute', a.fecha_inicio, now()) - a.minutos_contratados AS minutos_excedidos
FROM urbanbike_operativa.alquileres AS a FINAL
INNER JOIN urbanbike_operativa.usuarios AS u FINAL ON u.id = a.id_usuario
INNER JOIN urbanbike_operativa.bicicletas AS b FINAL ON b.id = a.id_bicicleta
WHERE a.estado = 'en_curso'
  AND dateDiff('minute', a.fecha_inicio, now()) > a.minutos_contratados
ORDER BY minutos_excedidos DESC;

-- S17. Infracciones activas por ciclista y tipo. Objetivo OT 13.
SELECT concat(u.nombre, ' ', u.apellido) AS ciclista,
       i.tipo, i.descripcion, i.monto_multa, i.fecha, i.estado
FROM urbanbike_operativa.infracciones AS i FINAL
INNER JOIN urbanbike_operativa.usuarios AS u FINAL ON u.id = i.id_usuario
WHERE i.estado = 'activa'
ORDER BY u.apellido, i.fecha;

-- S18. Flujo visual del alquiler. Objetivo OT 05. (obs. 8)
SELECT e.secuencia, e.estado_origen, e.estado_destino, e.fecha,
       e.rol_actor, e.observacion
FROM urbanbike_operativa.alquiler_eventos AS e
WHERE e.id_alquiler = {id_alquiler:UUID}
ORDER BY e.secuencia;
