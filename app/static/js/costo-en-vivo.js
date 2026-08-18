/* Cálculo compartido de tiempo/costo en vivo -- misma fórmula que ya
   usaba el cronómetro de ciclista/viaje_activo.html, reutilizada ahora
   también en empleado/vigilancia/devoluciones.html para que ambas
   pantallas muestren siempre el mismo número, sin duplicar la
   fórmula en dos lugares (ver docs/HOJA_DE_RUTA.md, sección 70). */

function segundosTranscurridos(fechaInicioISO) {
  const inicio = new Date(fechaInicioISO);
  return Math.max(0, Math.floor((Date.now() - inicio) / 1000));
}

// 5h de gracia sin cobro extra tras reportar la devolución -- debe
// coincidir siempre con el mismo número hardcodeado en
// empleado.py:vig_devolver() (retraso_min = ... - 300), que es el que
// de verdad calcula el cobro. Este archivo solo refleja ese cálculo,
// nunca lo decide.
const MINUTOS_GRACIA_DEMORA = 300;

/* Costo real de un viaje CON segmentos de modalidad (Tarea 9, plan
   "modalidad-tarifa-real"), con el mismo desglose que usa
   vig_devolver() (empleado.py, Tarea 7) para crear el pago:
   subtotal = suma de los segmentos de modalidad YA cerrados
   (subtotalCerrados, fijo -- ver alquileres_repo.total_segmentos_cerrados(),
   Tarea 6) + el segmento de modalidad todavía ABIERTO. El segmento
   abierto se calcula distinto según su modalidad, igual que
   vig_devolver(): 'hora' sigue el reloj REAL hasta 'ahora' -- incluso
   después de que el ciclista reportó la devolución, la espera hasta
   que Vigilancia confirma se sigue cobrando como parte del subtotal
   (ya NO se congela en fechaFinISO, a diferencia de la versión anterior
   de esta función -- ese congelamiento quedó obsoleto con el rediseño
   de la Tarea 7: la "espera" para 'hora' es tiempo de uso real, no
   demora); 'dia'/'semana' son tarifa plana, ya se cobran completas al
   abrir el segmento.
   El recargo por demora es un cargo aparte, 0 durante las 5h de
   gracia desde su punto de referencia (que también depende de la
   modalidad, ver abajo), después crece aparte -- y SIEMPRE se calcula
   con el precio de la modalidad 'hora' (precioHora), nunca con el
   precio de la modalidad activa: vig_devolver() hace exactamente eso
   (precio_hora_display, ver el bloque `else` de la rama 'dia'/'semana'
   en empleado.py) -- usar el precio de 'dia'/'semana' ahí daría un
   recargo mucho más alto que el que realmente se cobra. Si no se pasa
   precioHora (compatibilidad), se asume igual a precioModalidad (caso
   'hora', donde ambos son el mismo valor de todos modos).
   Si fechaFinISO todavía no existe (viaje 'activo', el ciclista no
   reportó nada aún), la gracia no aplica todavía en ningún caso. */
function costoDetallado(fechaInicioSegmentoISO, fechaFinISO, precioModalidad, modalidad, subtotalCerrados, precioHora) {
  const ahora = new Date();
  const inicioSegmento = new Date(fechaInicioSegmentoISO);
  if (precioHora === undefined || precioHora === null || isNaN(precioHora)) precioHora = precioModalidad;

  let subtotalSegmentoAbierto;
  if (modalidad === 'hora') {
    const horas = Math.max(0, (ahora - inicioSegmento) / 3600000);
    subtotalSegmentoAbierto = horas * precioModalidad;
  } else {
    subtotalSegmentoAbierto = precioModalidad; // tarifa plana, ya se cobra completa
  }
  const subtotal = subtotalCerrados + subtotalSegmentoAbierto;

  if (!fechaFinISO) {
    // Viaje todavia 'activo' (no reportado) -- la gracia por demora no
    // aplica todavia en ningun caso, igual que antes de este cambio.
    return { subtotal, recargoDemora: 0, enGracia: false, minutosParaRecargo: 0 };
  }

  // Punto de referencia de la gracia -- IDENTICO al que usa
  // vig_devolver() (Tarea 7): 'hora' cuenta desde que se reporto la
  // devolucion (fechaFinISO); 'dia'/'semana' cuentan desde que termina
  // la ventana comprada de ESE segmento, no desde el reporte.
  let referenciaGracia;
  if (modalidad === 'hora') {
    referenciaGracia = new Date(fechaFinISO);
  } else {
    const horasVentana = modalidad === 'dia' ? 24 : 24 * 7;
    referenciaGracia = new Date(inicioSegmento.getTime() + horasVentana * 3600000);
  }

  const minutosEspera = Math.max(0, (ahora - referenciaGracia) / 60000);
  const minutosRecargo = Math.max(0, minutosEspera - MINUTOS_GRACIA_DEMORA);
  return {
    subtotal,
    recargoDemora: (minutosRecargo / 60) * precioHora,
    enGracia: minutosEspera < MINUTOS_GRACIA_DEMORA,
    minutosParaRecargo: Math.max(0, MINUTOS_GRACIA_DEMORA - minutosEspera),
  };
}

function formatearDuracion(segundos) {
  const h = Math.floor(segundos / 3600);
  const m = Math.floor((segundos % 3600) / 60);
  const s = segundos % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}
