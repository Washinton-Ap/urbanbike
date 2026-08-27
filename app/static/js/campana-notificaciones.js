/* Campana de notificaciones (ver docs/Requerimientos_Mejoras_UrbanBike.md,
 * puntos 11.1 y 13). Centro simple: se carga al abrir el dropdown y al
 * cargar la página; el contador de no leídas se actualiza además con el
 * mismo sondeo de 4s que ya usa sesion-tiempo-real.js para la sesión
 * (window.UB_ACTUALIZAR_CAMPANA, ver ese archivo).
 */
(function () {
  var wrap = document.getElementById('campana-wrap');
  if (!wrap) return; // sin sesion activa (base.html no la renderiza)

  var toggle    = document.getElementById('campana-toggle');
  var dropdown  = document.getElementById('campana-dropdown');
  var lista     = document.getElementById('campana-lista');
  var contador  = document.getElementById('campana-contador');
  var btnTodas  = document.getElementById('campana-marcar-todas');
  var csrfToken = document.body.dataset.csrfToken || '';

  // Mismo lenguaje visual que UB.toast (notificaciones.js, punto 14): un
  // icono por tipo real, no un generico -- el color lo pone el CSS
  // (.campana-item.<tipo>, ver main.css).
  var ICONOS_POR_TIPO = {
    pago_aprobado: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
    falla: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    penalizacion: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    pago_pendiente: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
    orden_asignada: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    mensaje_soporte: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    membresia_por_vencer: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    membresia_vencida: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    infraccion: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    encuesta_satisfaccion: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
  };
  var ICONO_DEFECTO = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';

  // Tipos que representan una accion todavia pendiente de resolverse (pago
  // por cobrar/verificar, devolucion por validar) -- un clic NO las
  // descarta, solo desaparecen cuando la accion real se resuelve. El
  // backend tambien rechaza el POST de marcar-leida para estos tipos
  // (defensa en profundidad). Se llena desde `tipos_protegidos` de GET
  // /notificaciones (fuente real: notificaciones_repo.TIPOS_PROTEGIDOS) en
  // vez de duplicar la lista a mano acá, para que nunca queden
  // desincronizadas entre backend y frontend.
  var TIPOS_PROTEGIDOS = {};

  function postFormulario(url) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'csrf_token=' + encodeURIComponent(csrfToken),
    });
  }

  function formatearFecha(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleString('es-EC', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  }

  function actualizarContador(n) {
    if (n > 0) {
      contador.textContent = n > 99 ? '99+' : String(n);
      contador.style.display = '';
    } else {
      contador.style.display = 'none';
    }
  }

  // Expuesto para que sesion-tiempo-real.js pueda actualizar el numero sin
  // recargar la lista completa (el poll de 4s solo trae el conteo).
  window.UB_ACTUALIZAR_CAMPANA = actualizarContador;

  function renderLista(items) {
    if (!items.length) {
      lista.innerHTML = '<div class="campana-vacio">Sin notificaciones nuevas.</div>';
      return;
    }
    lista.innerHTML = '';
    items.forEach(function (n) {
      var pendiente = !!TIPOS_PROTEGIDOS[n.tipo];
      var el = document.createElement(n.enlace ? 'a' : 'div');
      el.className = 'campana-item ' + (n.tipo || '') + (pendiente ? ' campana-item-pendiente' : '');
      if (n.enlace) el.href = n.enlace;
      el.innerHTML =
        '<span class="campana-item-icono">' + (ICONOS_POR_TIPO[n.tipo] || ICONO_DEFECTO) + '</span>' +
        '<div class="campana-item-texto">' +
          '<div class="campana-item-titulo"></div>' +
          '<div class="campana-item-mensaje"></div>' +
          '<div class="campana-item-fecha"></div>' +
        '</div>';
      el.querySelector('.campana-item-titulo').textContent = n.titulo + (pendiente ? ' · pendiente' : '');
      el.querySelector('.campana-item-mensaje').textContent = n.mensaje;
      el.querySelector('.campana-item-fecha').textContent = formatearFecha(n.fecha);
      // Las de accion pendiente no se descartan con un clic -- solo
      // navegan (si tienen enlace); desaparecen cuando la accion real se
      // resuelve, no antes (ver TIPOS_PROTEGIDOS arriba).
      if (!pendiente) {
        el.addEventListener('click', function () {
          postFormulario('/notificaciones/' + n.id + '/marcar-leida').catch(function () {});
        });
      }
      lista.appendChild(el);
    });
  }

  function actualizarTiposProtegidos(lista) {
    TIPOS_PROTEGIDOS = {};
    (lista || []).forEach(function (tipo) { TIPOS_PROTEGIDOS[tipo] = true; });
  }

  function cargarLista() {
    fetch('/notificaciones', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        actualizarTiposProtegidos(data.tipos_protegidos);
        renderLista(data.items);
        actualizarContador(data.total);
      })
      .catch(function () {});
  }

  function abrir() {
    dropdown.style.display = 'block';
    cargarLista();
  }
  function cerrar() {
    dropdown.style.display = 'none';
  }

  toggle.addEventListener('click', function (e) {
    e.stopPropagation();
    if (dropdown.style.display === 'block') cerrar();
    else abrir();
  });
  document.addEventListener('click', function (e) {
    if (dropdown.style.display === 'block' && !wrap.contains(e.target)) cerrar();
  });

  btnTodas.addEventListener('click', function (e) {
    e.stopPropagation();
    postFormulario('/notificaciones/marcar-todas')
      .then(function () {
        // El backend salta las de TIPOS_PROTEGIDOS al marcar todas (siguen
        // pendientes de verdad) -- recargar la lista real en vez de asumir
        // que quedo vacia, para que esas sigan visibles.
        cargarLista();
      })
      .catch(function () {});
  });

  // Conteo inicial al cargar la pagina (sin abrir el dropdown) -- también
  // deja TIPOS_PROTEGIDOS listo antes de que el usuario abra el dropdown.
  fetch('/notificaciones', { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      actualizarTiposProtegidos(data.tipos_protegidos);
      actualizarContador(data.total);
    })
    .catch(function () {});
})();
