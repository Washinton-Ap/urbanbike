-- ============================================================
-- Datos de prueba minimos para verificar el esquema operativo
-- Los UUID se fijan a mano para poder relacionarlos entre tablas
-- ============================================================

-- Categorias (obs. 5)
INSERT INTO urbanbike_operativa.categorias (id, nombre, descripcion, es_premium, orden) VALUES
('11111111-0000-0000-0000-000000000001','Premium','Gama alta con componentes de competicion',1,1),
('11111111-0000-0000-0000-000000000002','Electrica','Asistida por motor electrico',1,2),
('11111111-0000-0000-0000-000000000003','Estandar','Uso general urbano',0,3),
('11111111-0000-0000-0000-000000000004','Montana','Doble suspension para terreno irregular',0,4);

-- Marcas (obs. 4)
INSERT INTO urbanbike_operativa.marcas (id, nombre, pais) VALUES
('22222222-0000-0000-0000-000000000001','Trek','Estados Unidos'),
('22222222-0000-0000-0000-000000000002','Giant','Taiwan'),
('22222222-0000-0000-0000-000000000003','Scott','Suiza');

-- Modelos con ficha tecnica completa (obs. 1 y 4: enfoque, marchas, frenos)
INSERT INTO urbanbike_operativa.modelos_bicicleta
(id, id_marca, id_categoria, nombre, anio, enfoque, marchas, tipo_frenos, material_cuadro, suspension, rodado, peso_kg, es_electrica, autonomia_km) VALUES
('33333333-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000001','11111111-0000-0000-0000-000000000001','Trek FX 3 Disc',2025,'urbano',21,'disco_hidraulico','aluminio','rigida',28,11.20,0,0),
('33333333-0000-0000-0000-000000000002','22222222-0000-0000-0000-000000000002','11111111-0000-0000-0000-000000000002','Giant Explore E+',2025,'paseo',8,'disco_hidraulico','aluminio','delantera',28,24.50,1,90),
('33333333-0000-0000-0000-000000000003','22222222-0000-0000-0000-000000000003','11111111-0000-0000-0000-000000000003','Scott Sub Cross 40',2024,'urbano',18,'zapata','aluminio','rigida',28,13.80,0,0);

-- Estaciones
INSERT INTO urbanbike_operativa.estaciones (id, codigo, nombre, direccion, latitud, longitud, capacidad) VALUES
('44444444-0000-0000-0000-000000000001','E-01','Estacion Central','Av. Siete de Octubre y Bolivar',-1.028500,-79.464200,40),
('44444444-0000-0000-0000-000000000002','E-02','Malecon','Malecon de Quevedo',-1.032100,-79.468900,25);

-- Bicicletas
INSERT INTO urbanbike_operativa.bicicletas
(id, codigo, id_modelo, id_estacion, numero_serie, estado, fecha_adquisicion, km_acumulados) VALUES
('55555555-0000-0000-0000-000000000001','UB-014','33333333-0000-0000-0000-000000000001','44444444-0000-0000-0000-000000000001','TRK2025A014','disponible','2025-03-10',842.50),
('55555555-0000-0000-0000-000000000002','EB-003','33333333-0000-0000-0000-000000000002','44444444-0000-0000-0000-000000000002','GNT2025E003','en_uso','2025-05-22',311.20),
('55555555-0000-0000-0000-000000000003','UB-072','33333333-0000-0000-0000-000000000003','44444444-0000-0000-0000-000000000001','SCT2024S072','mantenimiento','2024-11-05',1520.75);

-- Fotos (obs. 4)
INSERT INTO urbanbike_operativa.bicicleta_fotos (id_bicicleta, url, descripcion, es_principal, orden) VALUES
('55555555-0000-0000-0000-000000000001','/static/flota/ub014_1.jpg','Vista lateral',1,1),
('55555555-0000-0000-0000-000000000001','/static/flota/ub014_2.jpg','Detalle de frenos',0,2),
('55555555-0000-0000-0000-000000000002','/static/flota/eb003_1.jpg','Vista lateral',1,1);

-- Tarifas por bicicleta y modalidad (obs. 1: la tarifa va por bicicleta)
INSERT INTO urbanbike_operativa.tarifas
(id_bicicleta, modalidad, precio, minutos_gracia, recargo_minuto, vigente_desde) VALUES
('55555555-0000-0000-0000-000000000001','hora',2.50,10,0.08,'2026-01-01'),
('55555555-0000-0000-0000-000000000001','dia',14.00,30,0.08,'2026-01-01'),
('55555555-0000-0000-0000-000000000002','hora',3.75,10,0.12,'2026-01-01'),
('55555555-0000-0000-0000-000000000002','dia',20.00,30,0.12,'2026-01-01'),
('55555555-0000-0000-0000-000000000003','dia',9.00,30,0.05,'2026-01-01');

-- Promociones (obs. 1)
INSERT INTO urbanbike_operativa.promociones
(codigo, nombre, tipo_descuento, valor, aplica_a, dias_semana, fecha_inicio, fecha_fin) VALUES
('FINDE15','Descuento de fin de semana','porcentaje',15.00,'todas','6,7','2026-01-01','2026-12-31'),
('ESTUD20','Descuento estudiante','porcentaje',20.00,'todas','1,2,3,4,5','2026-01-01','2026-12-31');

-- Usuarios
INSERT INTO urbanbike_operativa.usuarios (id, codigo, nombre, apellido, email, rol) VALUES
('66666666-0000-0000-0000-000000000001','U-0001','Ana','Paredes','ana.paredes@correo.com','ciclista'),
('66666666-0000-0000-0000-000000000002','U-0002','Luis','Ochoa','luis.ochoa@correo.com','ciclista'),
('66666666-0000-0000-0000-000000000009','U-0009','Nadia','Bustos','nadia.bustos@urbanbike.ec','operacion'),
('66666666-0000-0000-0000-000000000010','U-0010','Franco','Salgado','franco.salgado@urbanbike.ec','mantenimiento');

-- Repuestos (obs. 2)
INSERT INTO urbanbike_operativa.repuestos
(id, codigo, nombre, categoria, stock_actual, stock_minimo, costo_unitario, proveedor) VALUES
('77777777-0000-0000-0000-000000000001','R-0001','Pastillas de freno','frenos',4,10,6.50,'Ciclo Repuestos S.A.'),
('77777777-0000-0000-0000-000000000002','R-0002','Camara rodado 28','neumaticos',7,15,4.20,'Ciclo Repuestos S.A.'),
('77777777-0000-0000-0000-000000000003','R-0003','Cadena 8 velocidades','transmision',6,8,9.75,'Bike Parts Ecuador'),
('77777777-0000-0000-0000-000000000004','R-0004','Luz delantera LED','luces',3,6,11.00,'Bike Parts Ecuador');

-- Checklist de devolucion (obs. 10)
INSERT INTO urbanbike_operativa.checklist_items (codigo, nombre, categoria, obligatorio, orden) VALUES
('CHK-01','Freno delantero','frenos',1,1),
('CHK-02','Freno trasero','frenos',1,2),
('CHK-03','Cambios y desviador','transmision',1,3),
('CHK-04','Cadena y engranajes','transmision',1,4),
('CHK-05','Presion de llanta delantera','ruedas',1,5),
('CHK-06','Presion de llanta trasera','ruedas',1,6),
('CHK-07','Radios y aro','ruedas',1,7),
('CHK-08','Luz delantera','luces',1,8),
('CHK-09','Luz trasera y reflectivos','luces',1,9),
('CHK-10','Cuadro sin fisuras ni golpes','cuadro',1,10),
('CHK-11','Sillin y manubrio ajustados','cuadro',1,11),
('CHK-12','Candado y accesorios completos','accesorios',1,12);

-- Plan de mantenimiento preventivo (obs. 9)
INSERT INTO urbanbike_operativa.planes_mantenimiento (id, nombre, tipo, intervalo_dias, intervalo_km, descripcion) VALUES
('88888888-0000-0000-0000-000000000001','Revision general trimestral','preventivo',90,500,'Ajuste de frenos, transmision y presion de llantas');

INSERT INTO urbanbike_operativa.mantenimientos_programados
(id_bicicleta, id_plan, fecha_programada, tipo, estado) VALUES
('55555555-0000-0000-0000-000000000001','88888888-0000-0000-0000-000000000001','2026-07-28','preventivo','pendiente'),
('55555555-0000-0000-0000-000000000002','88888888-0000-0000-0000-000000000001','2026-07-29','preventivo','pendiente');

-- Alquiler completo con su flujo (obs. 8)
INSERT INTO urbanbike_operativa.alquileres
(id, codigo, id_usuario, id_bicicleta, id_tarifa, id_estacion_inicio, modalidad,
 cantidad_contratada, minutos_contratados, fecha_inicio, fecha_fin, minutos_reales,
 estado, subtotal, descuento, recargo, total) VALUES
('99999999-0000-0000-0000-000000000001','A-010482','66666666-0000-0000-0000-000000000001',
 '55555555-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000000',
 '44444444-0000-0000-0000-000000000001','dia',1,1440,
 '2026-07-26 08:00:00','2026-07-26 17:30:00',570,'facturado',14.00,2.10,0.00,11.90);

INSERT INTO urbanbike_operativa.alquiler_eventos
(id_alquiler, secuencia, estado_origen, estado_destino, fecha, id_actor, rol_actor, observacion) VALUES
('99999999-0000-0000-0000-000000000001',1,'','reservado','2026-07-26 07:45:00','66666666-0000-0000-0000-000000000001','ciclista','Reserva en linea'),
('99999999-0000-0000-0000-000000000001',2,'reservado','en_curso','2026-07-26 08:00:00','66666666-0000-0000-0000-000000000009','operacion','Entrega en Estacion Central'),
('99999999-0000-0000-0000-000000000001',3,'en_curso','devuelto','2026-07-26 17:30:00','66666666-0000-0000-0000-000000000009','operacion','Devolucion en Estacion Central'),
('99999999-0000-0000-0000-000000000001',4,'devuelto','inspeccionado','2026-07-26 17:45:00','66666666-0000-0000-0000-000000000010','vigilancia','Checklist 12 de 12 sin dano'),
('99999999-0000-0000-0000-000000000001',5,'inspeccionado','facturado','2026-07-26 17:50:00','66666666-0000-0000-0000-000000000009','operacion','Factura 000004821');

-- Garantia con tarjeta (obs. 6)
INSERT INTO urbanbike_operativa.metodos_pago
(id, id_usuario, tipo, token_tarjeta, marca_tarjeta, ultimos4, exp_mes, exp_anio, es_principal) VALUES
('aaaaaaaa-0000-0000-0000-000000000001','66666666-0000-0000-0000-000000000001','tarjeta','tok_9f2b','visa','4417',9,2029,1);

INSERT INTO urbanbike_operativa.garantias
(id_alquiler, id_metodo_pago, monto_retenido, fondos_validados, codigo_autorizacion, estado, fecha_validacion) VALUES
('99999999-0000-0000-0000-000000000001','aaaaaaaa-0000-0000-0000-000000000001',25.00,1,'AUTH-77120','liberada','2026-07-26 07:46:00');

-- Facturacion (obs. 7)
INSERT INTO urbanbike_operativa.facturas
(id, serie, numero, id_alquiler, id_usuario, fecha_emision, subtotal, descuento, impuesto, total, estado) VALUES
('bbbbbbbb-0000-0000-0000-000000000001','001-001','000004821','99999999-0000-0000-0000-000000000001',
 '66666666-0000-0000-0000-000000000001','2026-07-26 17:50:00',14.00,2.10,1.43,13.33,'pagada');

INSERT INTO urbanbike_operativa.factura_detalle
(id_factura, linea, concepto, cantidad, precio_unitario, descuento, subtotal) VALUES
('bbbbbbbb-0000-0000-0000-000000000001',1,'Alquiler por dia UB-014 Trek FX 3 Disc',1,14.00,2.10,11.90);

-- Pagos y gastos del dia: entradas menos salidas
INSERT INTO urbanbike_operativa.pagos
(id_factura, id_alquiler, id_usuario, metodo, monto, estado, fecha, fecha_verificacion) VALUES
('bbbbbbbb-0000-0000-0000-000000000001','99999999-0000-0000-0000-000000000001','66666666-0000-0000-0000-000000000001','tarjeta',13.33,'verificado','2026-07-26 17:51:00','2026-07-26 17:51:00');

INSERT INTO urbanbike_operativa.pagos
(id_factura, id_alquiler, id_usuario, metodo, monto, estado, fecha) VALUES
('00000000-0000-0000-0000-000000000000','00000000-0000-0000-0000-000000000000','66666666-0000-0000-0000-000000000002','transferencia',4.50,'pendiente','2026-07-26 09:32:00');

INSERT INTO urbanbike_operativa.gastos (fecha, categoria, concepto, monto, id_registra) VALUES
('2026-07-26 10:05:00','repuestos','Compra de pastillas de freno',38.00,'66666666-0000-0000-0000-000000000010'),
('2026-07-26 13:20:00','combustible','Traslado de rebalanceo',12.00,'66666666-0000-0000-0000-000000000009');

-- Inspeccion de la devolucion (obs. 10)
INSERT INTO urbanbike_operativa.inspecciones
(id, id_alquiler, id_bicicleta, id_inspector, fecha_inicio, fecha_fin, estado, items_revisados, items_totales, tiene_dano) VALUES
('cccccccc-0000-0000-0000-000000000001','99999999-0000-0000-0000-000000000001','55555555-0000-0000-0000-000000000001',
 '66666666-0000-0000-0000-000000000010','2026-07-26 17:32:00','2026-07-26 17:45:00','certificada',12,12,0);

-- Orden de mantenimiento correctiva abierta (obs. 9)
INSERT INTO urbanbike_operativa.ordenes_mantenimiento
(id, codigo, id_bicicleta, origen, tipo_falla, prioridad, estado_reparacion, id_tecnico, diagnostico, fecha_apertura) VALUES
('dddddddd-0000-0000-0000-000000000001','OM-0311','55555555-0000-0000-0000-000000000003','reporte','frenos','alta',
 'espera_repuesto','66666666-0000-0000-0000-000000000010','Pastillas gastadas, requiere reemplazo','2026-07-25 09:10:00');

INSERT INTO urbanbike_operativa.movimientos_repuesto
(id_repuesto, tipo, cantidad, costo_unitario, id_orden, motivo, fecha, id_usuario) VALUES
('77777777-0000-0000-0000-000000000001','salida',2,6.50,'dddddddd-0000-0000-0000-000000000001','Consumo en orden OM-0311','2026-07-25 10:00:00','66666666-0000-0000-0000-000000000010');
