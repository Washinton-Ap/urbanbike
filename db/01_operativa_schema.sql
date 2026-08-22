-- ============================================================
-- UrbanBike S.A.  Base OPERATIVA en ClickHouse
-- Fase 1: catalogo de flota, tarifas, alquiler, garantias,
--         facturacion, repuestos, mantenimiento e inspeccion
-- Convenciones:
--   ReplacingMergeTree(version) = entidad con estado (se relee con FINAL)
--   MergeTree                   = evento inmutable (solo INSERT)
--   LowCardinality(String)      = campo tipo enumeracion
--   Decimal(10,2)               = dinero
-- ============================================================

CREATE DATABASE IF NOT EXISTS urbanbike_operativa;

-- ------------------------------------------------------------
-- 1. PERSONAS Y LUGARES
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS urbanbike_operativa.usuarios
(
    id            UUID DEFAULT generateUUIDv4(),
    codigo        String,                              -- U-0001
    nombre        String,
    apellido      String,
    email         String,
    telefono      String DEFAULT '',
    rol           LowCardinality(String),              -- ciclista|gerente|administrador|operacion|mantenimiento|vigilancia
    estado        LowCardinality(String) DEFAULT 'activo',  -- activo|inactivo|bloqueado
    motivo_bloqueo String DEFAULT '',
    fecha_registro DateTime DEFAULT now(),
    version       DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;
-- ORDER BY id (no (rol, id)): corregido 06-ago-2026, mismo riesgo que
-- bicicletas/alquileres/ordenes_mantenimiento (ver docs/HOJA_DE_RUTA.md
-- seccion 0) -- rol es mutable en teoria (cambio de rol de un usuario)
-- aunque todavia no se ha construido ningun flujo que lo actualice.

-- Roles y permisos gestionables desde una pantalla de Admin (ver
-- docs/HOJA_DE_RUTA.md seccion 29). Reemplaza, a futuro, el control de
-- acceso hoy hardcodeado en app/middleware/auth.py (ROLE_RULES, un
-- dict Python por prefijo de URL). Fase de hoy: solo las 3 tablas + los
-- 6 roles reales precargados -- el catalogo de permisos y la pantalla
-- de administracion quedan para una sesion aparte.
CREATE TABLE IF NOT EXISTS urbanbike_operativa.roles
(
    id          UUID DEFAULT generateUUIDv4(),
    slug        String,                                 -- valor real de user.rol_slug en sesion
    nombre      String,
    descripcion String DEFAULT '',
    es_sistema  UInt8 DEFAULT 0,                         -- protege los 6 roles reales de borrado accidental
    estado      LowCardinality(String) DEFAULT 'activo',
    version     DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;
-- ORDER BY id (no (estado, id)): mismo criterio que usuarios/bicicletas
-- -- estado es mutable (activar/desactivar un rol) desde el dia uno.

CREATE TABLE IF NOT EXISTS urbanbike_operativa.permisos
(
    id          UUID DEFAULT generateUUIDv4(),
    codigo      String,                                 -- unico, ej. 'bicicletas:crear', 'gerente:acceso'
    recurso     LowCardinality(String),
    accion      LowCardinality(String),
    descripcion String DEFAULT '',
    version     DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;

CREATE TABLE IF NOT EXISTS urbanbike_operativa.rol_permisos
(
    id_rol       UUID,
    id_permiso   UUID,
    otorgado_por UUID DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    fecha        DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (id_rol, id_permiso);
-- MergeTree, no ReplacingMergeTree: una concesion de permiso no se
-- "actualiza" in place -- se otorga (INSERT) o se revoca (DELETE), como
-- alquiler_eventos/bicicleta_eventos. otorgado_por en sentinela por
-- defecto: mismo motivo que bicicleta_eventos.id_actor (no se inventa
-- un actor si no llega uno real).

-- Excepciones de permiso por usuario individual, encima de
-- rol_permisos (ver docs/HOJA_DE_RUTA.md seccion 42). 3 estados por
-- (usuario, permiso): sin fila = sin excepcion (hereda del rol);
-- estado='otorgado' = tiene el permiso aunque su rol no se lo de;
-- estado='revocado' = no tiene el permiso aunque su rol si se lo de.
-- id_usuario = PocketBase users.id (identidad real de sesion), NO
-- urbanbike_operativa.usuarios.id -- admin y gerente no tienen fila ahi
-- hoy (confirmado en la seccion 42), y la excepcion debe poder aplicar
-- a cualquiera de los 6 roles. Mismo criterio que rol_permisos: MergeTree
-- simple, INSERT/DELETE reales, nunca UPDATE in place.
CREATE TABLE IF NOT EXISTS urbanbike_operativa.usuario_permisos
(
    id_usuario   String,
    id_permiso   UUID,
    estado       LowCardinality(String),                -- 'otorgado' | 'revocado'
    otorgado_por UUID DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    fecha        DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (id_usuario, id_permiso);

CREATE TABLE IF NOT EXISTS urbanbike_operativa.estaciones
(
    id         UUID DEFAULT generateUUIDv4(),
    codigo     String,                                 -- E-01
    nombre     String,
    direccion  String,
    latitud    Decimal(9,6),
    longitud   Decimal(9,6),
    capacidad  UInt16,
    activa     UInt8 DEFAULT 1,
    version    DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;

-- ------------------------------------------------------------
-- 2. CATALOGO DE FLOTA  (obs. 4 y 5: marca, partes, categorias, premium)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS urbanbike_operativa.marcas
(
    id      UUID DEFAULT generateUUIDv4(),
    nombre  String,
    pais    String DEFAULT '',
    activa  UInt8 DEFAULT 1,
    version DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;

CREATE TABLE IF NOT EXISTS urbanbike_operativa.categorias
(
    id          UUID DEFAULT generateUUIDv4(),
    nombre      LowCardinality(String),                -- Premium|Estandar|Electrica|Urbana|Montana
    descripcion String DEFAULT '',
    es_premium  UInt8 DEFAULT 0,                       -- obs. 5: catalogo premium
    orden       UInt8 DEFAULT 0,
    activa      UInt8 DEFAULT 1,
    version     DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;

-- Ficha tecnica del modelo: aqui viven marchas, frenos y demas partes
CREATE TABLE IF NOT EXISTS urbanbike_operativa.modelos_bicicleta
(
    id             UUID DEFAULT generateUUIDv4(),
    id_marca       UUID,
    id_categoria   UUID,
    nombre         String,                             -- Trek FX 3 Disc
    anio           UInt16,
    enfoque        LowCardinality(String),             -- obs. 1: urbano|montana|ruta|paseo|carga
    marchas        UInt8,                              -- obs. 4
    tipo_frenos    LowCardinality(String),             -- disco_hidraulico|disco_mecanico|zapata|contrapedal
    material_cuadro LowCardinality(String),            -- aluminio|acero|carbono
    suspension     LowCardinality(String) DEFAULT 'rigida', -- rigida|delantera|doble
    rodado         UInt8,                              -- 26|27|29
    peso_kg        Decimal(5,2),
    es_electrica   UInt8 DEFAULT 0,
    autonomia_km   UInt16 DEFAULT 0,
    activo         UInt8 DEFAULT 1,
    version        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (id_categoria, id_marca, id);

-- Unidad fisica de la flota
CREATE TABLE IF NOT EXISTS urbanbike_operativa.bicicletas
(
    id               UUID DEFAULT generateUUIDv4(),
    codigo           String,                           -- UB-014
    id_modelo        UUID,
    id_estacion      UUID,
    numero_serie     String,
    estado           LowCardinality(String) DEFAULT 'disponible', -- disponible|en_uso|mantenimiento|retirada
    fecha_adquisicion Date,
    km_acumulados    Decimal(10,2) DEFAULT 0,
    minutos_uso      UInt32 DEFAULT 0,
    fecha_ultimo_mantenimiento Date DEFAULT toDate('1970-01-01'),
    observacion      String DEFAULT '',
    version          DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;
-- ORDER BY id (no (estado, id)): estado cambia todo el tiempo en la vida
-- real de una bicicleta (disponible/en_uso/mantenimiento/retirada). Un
-- ALTER ... UPDATE de una columna que esta en la clave de orden falla
-- (CANNOT_UPDATE_COLUMN), y un INSERT "nueva version" con estado
-- distinto no reemplaza la fila vieja, crea una fila duplicada (la
-- deduplicacion de ReplacingMergeTree exige la MISMA clave de orden
-- completa). Bug real encontrado y corregido el 30-jul-2026 al construir
-- el WorkPanel de bicicletas (ver docs/HOJA_DE_RUTA.md).

-- obs. 4: fotos de la bicicleta
CREATE TABLE IF NOT EXISTS urbanbike_operativa.bicicleta_fotos
(
    id           UUID DEFAULT generateUUIDv4(),
    id_bicicleta UUID,
    url          String,
    descripcion  String DEFAULT '',
    es_principal UInt8 DEFAULT 0,
    orden        UInt8 DEFAULT 0,
    version      DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (id_bicicleta, orden, id);

-- Linea de tiempo de la bicicleta (mismo patron que alquiler_eventos):
-- necesaria para poder calcular resumen_mensual_flota en
-- urbanbike_estrategica algun dia (ver docs/HOJA_DE_RUTA.md, pendiente
-- #12 de la seccion 6) -- hoy solo existe el estado actual (snapshot)
-- de bicicletas.estado, sin ningun historial de cuando cambio.
-- Empieza a llenarse desde que bicicletas_repo.actualizar() se
-- modifico para escribirla (07-ago-2026, ver seccion 28 de la hoja de
-- ruta) -- NO se reconstruyen los cambios de estado anteriores a esa
-- fecha (inventar esas fechas seria peor que no tenerlas).
CREATE TABLE IF NOT EXISTS urbanbike_operativa.bicicleta_eventos
(
    id_bicicleta   UUID,
    estado_origen  LowCardinality(String),
    estado_destino LowCardinality(String),
    fecha          DateTime DEFAULT now(),
    id_actor       UUID DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    rol_actor      LowCardinality(String) DEFAULT '',
    observacion    String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(fecha)
ORDER BY (id_bicicleta, fecha);
-- id_actor/rol_actor sin poblar todavia: bicicletas_repo.actualizar()
-- no recibe el actor real desde ninguno de sus 5 llamadores hoy (a
-- diferencia de alquiler_eventos, cuyos llamadores si pasan el actor
-- real) -- se registra el sentinela documentado en vez de inventar un
-- actor. Pendiente para cuando se decida ampliar la firma de
-- actualizar() en una sesion aparte.

-- ------------------------------------------------------------
-- 3. TARIFAS Y PROMOCIONES  (obs. 1: la tarifa va por categoria de
--    bicicleta y tipo de membresia, no por bicicleta individual;
--    modalidad hora|dia|semana)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS urbanbike_operativa.tarifas
(
    id             UUID DEFAULT generateUUIDv4(),
    id_categoria   UUID,                               -- FK a categorias
    tipo_membresia LowCardinality(String),             -- member|casual
    modalidad      LowCardinality(String),             -- hora|dia|semana
    precio         Decimal(10,2),
    minutos_gracia UInt16 DEFAULT 0,
    recargo_minuto Decimal(10,2) DEFAULT 0,            -- excedente del tiempo contratado
    vigente_desde  Date,
    vigente_hasta  Date DEFAULT toDate('2099-12-31'),
    estado         LowCardinality(String) DEFAULT 'vigente', -- vigente|historica
    version        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;
-- ORDER BY id (no (id_categoria, tipo_membresia, modalidad, vigente_desde)):
-- corregido preventivamente 06-ago-2026, ver docs/HOJA_DE_RUTA.md seccion 0.
-- Ninguna de esas columnas cambiaba de valor en el uso real hasta hoy (la
-- tabla solo se leia, nunca se editaba en vivo), pero se recreo con ORDER BY
-- id antes de construir el primer editor real de tarifas para no repetir el
-- mismo bug de bicicletas/alquileres apenas alguien corrija una categoria o
-- modalidad de una tarifa existente.

CREATE TABLE IF NOT EXISTS urbanbike_operativa.promociones
(
    id             UUID DEFAULT generateUUIDv4(),
    codigo         String,                             -- FINDE15
    nombre         String,
    tipo_descuento LowCardinality(String),             -- porcentaje|monto
    valor          Decimal(10,2),
    aplica_a       LowCardinality(String) DEFAULT 'todas', -- todas|categoria|modalidad|bicicleta
    id_referencia  String DEFAULT '',                  -- id de la categoria, modalidad o bicicleta
    dias_semana    String DEFAULT '1,2,3,4,5,6,7',     -- 6,7 = fin de semana
    fecha_inicio   Date,
    fecha_fin      Date,
    usos_maximos   UInt32 DEFAULT 0,                   -- 0 = sin limite
    usos_actuales  UInt32 DEFAULT 0,
    estado         LowCardinality(String) DEFAULT 'activa', -- activa|pausada|vencida
    solo_member    UInt8 DEFAULT 0,                    -- punto 4: promo exclusiva para suscriptores
    version        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;
-- ORDER BY id (no (estado, fecha_fin, id)): corregido 06-ago-2026, ver
-- docs/HOJA_DE_RUTA.md seccion 0. estado sí es mutable (activa ->
-- pausada|vencida); fecha_fin tambien puede editarse (extender una
-- promocion).

-- ------------------------------------------------------------
-- 4. ALQUILER Y SU FLUJO  (obs. 8: flujo visual del alquiler)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS urbanbike_operativa.alquileres
(
    id                 UUID DEFAULT generateUUIDv4(),
    codigo             String,                         -- A-010482
    id_usuario         UUID,
    id_bicicleta       UUID,
    id_tarifa          UUID,
    id_promocion       String DEFAULT '',
    id_estacion_inicio UUID,
    id_estacion_fin    String DEFAULT '',
    modalidad          LowCardinality(String),         -- hora|dia|semana
    cantidad_contratada UInt16,                        -- 2 horas, 3 dias, etc.
    minutos_contratados UInt32,
    fecha_reserva      DateTime DEFAULT now(),
    fecha_inicio       DateTime,
    fecha_fin          DateTime DEFAULT toDateTime('1970-01-01 00:00:00'),
    minutos_reales     UInt32 DEFAULT 0,
    estado             LowCardinality(String) DEFAULT 'reservado',
        -- reservado|en_curso|devuelto|inspeccionado|facturado|cerrado|cancelado
    subtotal           Decimal(10,2) DEFAULT 0,
    descuento          Decimal(10,2) DEFAULT 0,
    recargo            Decimal(10,2) DEFAULT 0,
    total              Decimal(10,2) DEFAULT 0,
    es_prueba          UInt8 DEFAULT 0,               -- 1 = prueba de desarrollo real,
                                                       -- excluir de KPI/informes (WHERE es_prueba = 0)
    id_origen_pocketbase String DEFAULT '',           -- viajes.id de PocketBase si este alquiler
                                                       -- viene de la migracion (etl/07); '' si no.
                                                       -- Clave real de idempotencia del ETL 07 y
                                                       -- reemplaza el enlace fragil por texto libre
                                                       -- en alquiler_eventos.observacion (ver
                                                       -- docs/HOJA_DE_RUTA.md seccion 17, resuelto).
    version            DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(fecha_reserva)
ORDER BY (fecha_reserva, id);
-- ORDER BY (fecha_reserva, id), no (estado, ...): estado avanza todo el
-- tiempo (reservado->en_curso->devuelto->facturado / cancelado). Mismo
-- bug que se encontro y corrigio en bicicletas el 30-jul-2026 (ver
-- docs/HOJA_DE_RUTA.md seccion 0): con estado en la clave de orden, un
-- ALTER ... UPDATE estado falla con CANNOT_UPDATE_COLUMN. Corregido
-- aqui el mismo dia al construir el WorkPanel de alquileres.

-- Linea de tiempo del alquiler: alimenta el flujo visual
CREATE TABLE IF NOT EXISTS urbanbike_operativa.alquiler_eventos
(
    id_alquiler    UUID,
    secuencia      UInt8,
    estado_origen  LowCardinality(String),
    estado_destino LowCardinality(String),
    fecha          DateTime DEFAULT now(),
    id_actor       UUID,
    rol_actor      LowCardinality(String),
    observacion    String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(fecha)
ORDER BY (id_alquiler, secuencia);

-- ------------------------------------------------------------
-- 5. GARANTIA Y COBRO AUTOMATICO  (obs. 6)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS urbanbike_operativa.metodos_pago
(
    id             UUID DEFAULT generateUUIDv4(),
    id_usuario     UUID,
    tipo           LowCardinality(String),             -- tarjeta|transferencia|efectivo
    token_tarjeta  String DEFAULT '',                  -- token de la pasarela, nunca el numero
    marca_tarjeta  LowCardinality(String) DEFAULT '',  -- visa|mastercard|amex
    ultimos4       FixedString(4) DEFAULT '0000',
    exp_mes        UInt8 DEFAULT 0,
    exp_anio       UInt16 DEFAULT 0,
    es_principal   UInt8 DEFAULT 0,
    estado         LowCardinality(String) DEFAULT 'activo', -- activo|vencido|revocado
    version        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (id_usuario, id);

CREATE TABLE IF NOT EXISTS urbanbike_operativa.garantias
(
    id                UUID DEFAULT generateUUIDv4(),
    id_alquiler       UUID,
    id_metodo_pago    UUID,
    monto_retenido    Decimal(10,2),
    fondos_validados  UInt8 DEFAULT 0,
    codigo_autorizacion String DEFAULT '',
    estado            LowCardinality(String) DEFAULT 'pendiente',
        -- pendiente|validada|rechazada|liberada|ejecutada
    fecha_solicitud   DateTime DEFAULT now(),
    fecha_validacion  DateTime DEFAULT toDateTime('1970-01-01 00:00:00'),
    fecha_liberacion  DateTime DEFAULT toDateTime('1970-01-01 00:00:00'),
    motivo_rechazo    String DEFAULT '',
    version           DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;
-- ORDER BY id (no (estado, id_alquiler)): corregido 06-ago-2026, ver
-- docs/HOJA_DE_RUTA.md seccion 0. estado sí es mutable (pendiente ->
-- validada -> ... -> ejecutada).

CREATE TABLE IF NOT EXISTS urbanbike_operativa.cobros_automaticos
(
    id             UUID DEFAULT generateUUIDv4(),
    id_garantia    UUID,
    id_alquiler    UUID,
    motivo         LowCardinality(String),             -- no_devolucion|robo|dano|recargo_tiempo
    monto          Decimal(10,2),
    estado         LowCardinality(String) DEFAULT 'pendiente', -- pendiente|ejecutado|fallido|reversado
    fecha_ejecucion DateTime DEFAULT toDateTime('1970-01-01 00:00:00'),
    referencia_pasarela String DEFAULT '',
    detalle        String DEFAULT '',
    version        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;
-- ORDER BY id (no (estado, id_alquiler, id)): corregido 06-ago-2026,
-- ver docs/HOJA_DE_RUTA.md seccion 0. estado sí es mutable (pendiente
-- -> ejecutado/fallido -> reversado).

-- ------------------------------------------------------------
-- 6. FACTURACION Y CAJA  (obs. 7 y verificacion de ganancia)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS urbanbike_operativa.facturas
(
    id           UUID DEFAULT generateUUIDv4(),
    serie        String DEFAULT '001-001',
    numero       String,                               -- 000004821
    id_alquiler  UUID,
    id_usuario   UUID,
    fecha_emision DateTime DEFAULT now(),
    subtotal     Decimal(10,2),
    descuento    Decimal(10,2) DEFAULT 0,
    impuesto     Decimal(10,2) DEFAULT 0,
    total        Decimal(10,2),
    estado       LowCardinality(String) DEFAULT 'emitida', -- emitida|pagada|anulada
    version      DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(fecha_emision)
ORDER BY (fecha_emision, numero);

CREATE TABLE IF NOT EXISTS urbanbike_operativa.factura_detalle
(
    id             UUID DEFAULT generateUUIDv4(),
    id_factura     UUID,
    linea          UInt8,
    concepto       String,                             -- Alquiler por dia UB-014
    cantidad       Decimal(10,2),
    precio_unitario Decimal(10,2),
    descuento      Decimal(10,2) DEFAULT 0,
    subtotal       Decimal(10,2),
    version        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (id_factura, linea);

CREATE TABLE IF NOT EXISTS urbanbike_operativa.pagos
(
    id            UUID DEFAULT generateUUIDv4(),
    id_factura    UUID,
    id_alquiler   UUID,
    id_usuario    UUID,
    metodo        LowCardinality(String),              -- tarjeta|transferencia|efectivo|automatico
    monto         Decimal(10,2),
    estado        LowCardinality(String) DEFAULT 'pendiente', -- pendiente|verificado|rechazado
    concepto      LowCardinality(String) DEFAULT 'alquiler', -- alquiler|membresia|cargo_danos -- agregada 11-ago-2026 (ALTER TABLE en vivo, ver seccion de membresias): sin romper ninguna fila real, todas las existentes son 'alquiler' por default
    fecha         DateTime DEFAULT now(),
    id_verificador String DEFAULT '',
    fecha_verificacion DateTime DEFAULT toDateTime('1970-01-01 00:00:00'),
    referencia    String DEFAULT '',
    comprobante_url String DEFAULT '',
    version       DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(fecha)
ORDER BY (fecha, id);
-- ORDER BY (fecha, id), no (estado, fecha, id): corregido 06-ago-2026,
-- ver docs/HOJA_DE_RUTA.md seccion 0. estado sí es mutable (pendiente ->
-- verificado|rechazado). fecha se conserva (inmutable, coincide con la
-- particion mensual), mismo criterio que alquileres.

-- Cuentas propias del negocio para pagos por transferencia (existe en
-- PocketBase, sin equivalente previo en este esquema).
CREATE TABLE IF NOT EXISTS urbanbike_operativa.cuentas_bancarias
(
    id            UUID DEFAULT generateUUIDv4(),
    banco         String,
    tipo_cuenta   LowCardinality(String) DEFAULT '',   -- ahorros|corriente
    numero_cuenta String,
    titular       String DEFAULT '',
    activa        UInt8 DEFAULT 1,
    version       DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;

-- Salidas de dinero: sin esto no se puede calcular la ganancia real
CREATE TABLE IF NOT EXISTS urbanbike_operativa.gastos
(
    id           UUID DEFAULT generateUUIDv4(),
    fecha        DateTime DEFAULT now(),
    categoria    LowCardinality(String),               -- repuestos|nomina|servicios|combustible|otros
    concepto     String,
    monto        Decimal(10,2),
    id_referencia String DEFAULT '',                   -- id de la orden de mantenimiento, si aplica
    id_registra  UUID,
    comprobante  String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(fecha)
ORDER BY (fecha, categoria);

-- ------------------------------------------------------------
-- 7. REPUESTOS  (obs. 2)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS urbanbike_operativa.repuestos
(
    id             UUID DEFAULT generateUUIDv4(),
    codigo         String,                             -- R-0007
    nombre         String,
    categoria      LowCardinality(String),             -- frenos|transmision|neumaticos|luces|cuadro|accesorios
    unidad         LowCardinality(String) DEFAULT 'unidad',
    stock_actual   Int32 DEFAULT 0,
    stock_minimo   Int32 DEFAULT 0,
    costo_unitario Decimal(10,2),
    proveedor      String DEFAULT '',
    ubicacion      String DEFAULT '',
    activo         UInt8 DEFAULT 1,
    version        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;
-- ORDER BY id (no (categoria, id)): corregido 06-ago-2026, ver
-- docs/HOJA_DE_RUTA.md seccion 0. categoria es editable en teoria
-- (reclasificar un repuesto); stock_actual (lo que sí cambia todo el
-- tiempo) ya no estaba en la clave, eso siempre estuvo bien.

CREATE TABLE IF NOT EXISTS urbanbike_operativa.movimientos_repuesto
(
    id           UUID DEFAULT generateUUIDv4(),
    id_repuesto  UUID,
    tipo         LowCardinality(String),               -- entrada|salida|ajuste
    cantidad     Int32,
    costo_unitario Decimal(10,2) DEFAULT 0,
    id_orden     String DEFAULT '',
    motivo       String DEFAULT '',
    fecha        DateTime DEFAULT now(),
    id_usuario   UUID
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(fecha)
ORDER BY (id_repuesto, fecha);

-- ------------------------------------------------------------
-- 8. MANTENIMIENTO PREVENTIVO Y CORRECTIVO  (obs. 9)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS urbanbike_operativa.planes_mantenimiento
(
    id            UUID DEFAULT generateUUIDv4(),
    nombre        String,                              -- Revision general cada 90 dias
    id_categoria  String DEFAULT '',                   -- vacio = aplica a toda la flota
    tipo          LowCardinality(String) DEFAULT 'preventivo',
    intervalo_dias UInt16 DEFAULT 0,
    intervalo_km  UInt32 DEFAULT 0,
    descripcion   String DEFAULT '',
    activo        UInt8 DEFAULT 1,
    version       DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;

CREATE TABLE IF NOT EXISTS urbanbike_operativa.mantenimientos_programados
(
    id                UUID DEFAULT generateUUIDv4(),
    id_bicicleta      UUID,
    id_plan           UUID,
    fecha_programada  Date,
    tipo              LowCardinality(String) DEFAULT 'preventivo',
    estado            LowCardinality(String) DEFAULT 'pendiente', -- pendiente|en_proceso|completado|omitido
    id_orden_generada String DEFAULT '',
    observacion       String DEFAULT '',
    version           DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;
-- ORDER BY id (no (estado, fecha_programada, id)): corregido
-- 06-ago-2026, mismo riesgo que ordenes_mantenimiento (ver
-- docs/HOJA_DE_RUTA.md seccion 0) -- estado sí es mutable (pendiente ->
-- en_proceso -> completado|omitido).

CREATE TABLE IF NOT EXISTS urbanbike_operativa.ordenes_mantenimiento
(
    id               UUID DEFAULT generateUUIDv4(),
    codigo           String,                           -- OM-0311
    id_bicicleta     UUID,
    origen           LowCardinality(String),           -- preventivo|devolucion|reporte|inspeccion
    id_programado    String DEFAULT '',
    id_inspeccion    String DEFAULT '',
    tipo_falla       LowCardinality(String),           -- frenos|transmision|neumatico|electrico|estructural|otro
    prioridad        LowCardinality(String) DEFAULT 'media', -- alta|media|baja
    estado_reparacion LowCardinality(String) DEFAULT 'abierta',
        -- abierta|diagnostico|en_reparacion|espera_repuesto|cerrada
    id_tecnico       UUID,
    diagnostico      String DEFAULT '',
    fecha_apertura   DateTime DEFAULT now(),
    fecha_limite     DateTime DEFAULT toDateTime('1970-01-01 00:00:00'), -- punto 2.7: plazo segun prioridad, calculado en ordenes_repo.crear()
    fecha_cierre     DateTime DEFAULT toDateTime('1970-01-01 00:00:00'),
    costo_repuestos  Decimal(10,2) DEFAULT 0,
    costo_mano_obra  Decimal(10,2) DEFAULT 0,
    version          DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(fecha_apertura)
ORDER BY id;  -- corregido 30-jul-2026: estado_reparacion es mutable (mismo bug
              -- que bicicletas/alquileres, ver docs/HOJA_DE_RUTA.md seccion 0)

CREATE TABLE IF NOT EXISTS urbanbike_operativa.orden_repuesto
(
    id             UUID DEFAULT generateUUIDv4(),
    id_orden       UUID,
    id_repuesto    UUID,
    cantidad       Int32,
    costo_unitario Decimal(10,2),
    subtotal       Decimal(10,2),
    version        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (id_orden, id_repuesto);

-- ------------------------------------------------------------
-- 9. INSPECCION DE DEVOLUCION  (obs. 10: checklist completo)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS urbanbike_operativa.checklist_items
(
    id          UUID DEFAULT generateUUIDv4(),
    codigo      String,                                -- CHK-01
    nombre      String,                                -- Frenos delanteros
    categoria   LowCardinality(String),                -- frenos|transmision|ruedas|luces|cuadro|accesorios
    descripcion String DEFAULT '',
    obligatorio UInt8 DEFAULT 1,
    orden       UInt8 DEFAULT 0,
    activo      UInt8 DEFAULT 1,
    version     DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (categoria, orden, id);

CREATE TABLE IF NOT EXISTS urbanbike_operativa.inspecciones
(
    id                UUID DEFAULT generateUUIDv4(),
    id_alquiler       UUID,
    id_bicicleta      UUID,
    id_inspector      UUID,
    fecha_inicio      DateTime DEFAULT now(),
    fecha_fin         DateTime DEFAULT toDateTime('1970-01-01 00:00:00'),
    estado            LowCardinality(String) DEFAULT 'pendiente', -- pendiente|en_proceso|certificada
    items_revisados   UInt8 DEFAULT 0,
    items_totales     UInt8 DEFAULT 0,
    tiene_dano        UInt8 DEFAULT 0,
    id_orden_generada String DEFAULT '',
    observacion       String DEFAULT '',
    version           DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;
-- ORDER BY id (no (estado, id_alquiler)): corregido 06-ago-2026, ver
-- docs/HOJA_DE_RUTA.md seccion 0. estado sí es mutable (pendiente ->
-- en_proceso -> certificada).

CREATE TABLE IF NOT EXISTS urbanbike_operativa.inspeccion_detalle
(
    id            UUID DEFAULT generateUUIDv4(),
    id_inspeccion UUID,
    id_item       UUID,
    resultado     LowCardinality(String),              -- ok|dano_leve|dano_grave|faltante
    observacion   String DEFAULT '',
    foto_url      String DEFAULT '',
    version       DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (id_inspeccion, id_item);

-- ------------------------------------------------------------
-- 10. INFRACCIONES Y AUDITORIA
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS urbanbike_operativa.infracciones
(
    id           UUID DEFAULT generateUUIDv4(),
    id_usuario   UUID,
    id_alquiler  String DEFAULT '',
    tipo         LowCardinality(String),               -- retraso|dano|no_devolucion|mal_uso
    descripcion  String DEFAULT '',
    monto_multa  Decimal(10,2) DEFAULT 0,
    estado       LowCardinality(String) DEFAULT 'activa', -- activa|pagada|anulada
    fecha        DateTime DEFAULT now(),
    version      DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(fecha)
ORDER BY (fecha, id);
-- ORDER BY (fecha, id), no (estado, id_usuario, fecha): corregido
-- 06-ago-2026, ver docs/HOJA_DE_RUTA.md seccion 0. estado sí es mutable
-- (activa -> pagada|anulada). fecha se conserva (inmutable, coincide
-- con la particion mensual), mismo criterio que pagos/alquileres.

CREATE TABLE IF NOT EXISTS urbanbike_operativa.auditoria
(
    fecha      DateTime DEFAULT now(),
    id_usuario UUID,
    usuario    String,
    modulo     LowCardinality(String),
    accion     LowCardinality(String),
    detalle    String DEFAULT '',
    ip         String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(fecha)
ORDER BY (fecha, modulo);

-- ------------------------------------------------------------
-- 11. MEMBRESIAS  (agregada 11-ago-2026, ver docs/HOJA_DE_RUTA.md)
-- ------------------------------------------------------------

-- Precio versionado de la membresia mensual, mismo patron que tarifas
-- (vigencia por fecha + estado vigente/historica). No tiene categoria
-- ni tipo_membresia -- es un solo producto, un solo precio a la vez.
CREATE TABLE IF NOT EXISTS urbanbike_operativa.membresia_tarifa
(
    id             UUID DEFAULT generateUUIDv4(),
    precio         Decimal(10,2),
    vigente_desde  Date,
    vigente_hasta  Date DEFAULT toDate('2099-12-31'),
    estado         LowCardinality(String) DEFAULT 'vigente', -- vigente|historica
    version        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;

-- Historial real de membresias por ciclista -- append-only a proposito
-- (MergeTree, no ReplacingMergeTree): cada compra/renovacion/vencimiento
-- es una fila nueva, nunca se actualiza una existente. Mismo patron que
-- alquiler_eventos/bicicleta_eventos (bitacora, no entidad mutable) --
-- evita desde el diseño la clase de bug de ORDER BY que se corrigio once
-- veces en este proyecto (seccion 0), porque aqui no hay ningun
-- ALTER ... UPDATE. El estado actual de un ciclista es su fila mas
-- reciente por (fecha_inicio, fecha_registro) -- ver
-- app/db/membresias_repo.py:esta_activa().
CREATE TABLE IF NOT EXISTS urbanbike_operativa.membresias
(
    id             UUID DEFAULT generateUUIDv4(),
    id_usuario     UUID,                                -- FK a usuarios.id
    fecha_inicio   Date,                                 -- inicio de ESTE periodo
    fecha_fin      Date,                                 -- vencimiento de este periodo
    estado         LowCardinality(String),               -- activa|vencida|cancelada
    precio         Decimal(10,2),                        -- precio cobrado este periodo (historial real)
    id_pago        UUID DEFAULT toUUID('00000000-0000-0000-0000-000000000000'), -- FK a pagos.id; sentinela si no hubo cobro (renovacion fallida)
    origen         LowCardinality(String),               -- compra|renovacion_automatica|renovacion_fallida
    fecha_registro DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(fecha_inicio)
ORDER BY (id_usuario, fecha_inicio, fecha_registro);
