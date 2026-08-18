(function () {
  // Mismo patrón que lightbox.js: delegación de eventos sobre document,
  // funciona con elementos ya presentes en el DOM y con los que se
  // insertan después vía JS (modales, filas de tabla), sin tener que
  // volver a "escanear" la página ni tocar cada plantilla.

  var PATRON_EXPORTACION = /\/(excel|pdf)$/;
  var TIEMPO_SEGURIDAD_DESCARGA_MS = 8000;

  function esClicNormal(e) {
    // Clic izquierdo simple, sin modificadores -- Ctrl/Cmd/Shift/Alt+clic
    // abre en pestaña nueva o hace otra cosa que el navegador ya maneja
    // solo, no debe disparar ni el spinner ni la barra de progreso.
    return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
  }

  function marcarCargando(el) {
    el.classList.add('is-loading');
    if (el.tagName === 'BUTTON' || el.tagName === 'INPUT') el.disabled = true;
  }

  // ── Mecanismo A: formularios ────────────────────────────────────────
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.hasAttribute('data-no-loading')) return;

    var boton = e.submitter ||
      form.querySelector('button[type="submit"], button:not([type]), input[type="submit"]');
    if (!boton || boton.hasAttribute('data-no-loading')) return;

    marcarCargando(boton);
  });

  // ── Mecanismo A (exportaciones) + Mecanismo B (navegación interna) ──
  document.addEventListener('click', function (e) {
    // Bubble, no capture: para cuando llega acá, cualquier
    // preventDefault() de un handler más específico (ej. el lightbox del
    // avatar en base.html, las pestañas de checklist_devolucion.html) ya
    // corrió -- si el clic no va a navegar de verdad, no hay nada que
    // mostrar.
    if (e.defaultPrevented) return;
    if (!esClicNormal(e)) return;

    var link = e.target.closest('a[href]');
    if (!link) return;
    if (link.hasAttribute('data-no-loading')) return;
    if (link.hasAttribute('download')) return;
    if (link.target && link.target !== '' && link.target !== '_self') return;

    var href = link.getAttribute('href') || '';
    if (!href || href.charAt(0) === '#' ||
        href.indexOf('javascript:') === 0 ||
        href.indexOf('mailto:') === 0 ||
        href.indexOf('tel:') === 0) return;

    var url;
    try {
      url = new URL(href, window.location.href);
    } catch (err) {
      return;
    }
    if (url.origin !== window.location.origin) return;

    if (PATRON_EXPORTACION.test(url.pathname)) {
      // Exportación real (Excel/PDF): la descarga no navega fuera de la
      // página, así que no hay evento de "terminó" -- se reactiva sola
      // tras un tiempo de seguridad fijo.
      if (link.classList.contains('is-loading')) {
        e.preventDefault();
        return;
      }
      marcarCargando(link);
      setTimeout(function () {
        link.classList.remove('is-loading');
      }, TIEMPO_SEGURIDAD_DESCARGA_MS);
      return;
    }

    // Navegación interna real: la barra se destruye sola cuando el
    // navegador reemplaza la página, no hace falta ocultarla a mano.
    mostrarBarraProgreso();
  });

  function mostrarBarraProgreso() {
    var barra = document.getElementById('ub-progreso');
    if (!barra) {
      barra = document.createElement('div');
      barra.id = 'ub-progreso';
      document.body.appendChild(barra);
    }
    barra.classList.remove('ub-progreso-avanzar');
    void barra.offsetWidth; // fuerza reflow para poder reiniciar la animación
    barra.classList.add('ub-progreso-avanzar');
  }
})();
