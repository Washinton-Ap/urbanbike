/* Componente único de notificaciones UrbanBike (ver docs/Requerimientos_Mejoras_UrbanBike.md,
 * punto 14): toast flotante autocerrable + modal de confirmación, para reemplazar
 * alert()/confirm() nativos y los flash messages sin diseñar. Expone window.UB.
 *
 * Uso:
 *   UB.toast('Reporte exportado.', 'success');
 *   UB.toast('El administrador Ana cerró tu sesión.', 'info', 5000);
 *   const ok = await UB.confirm('¿Eliminar esta cuenta?', { peligro: true });
 *
 * Para formularios que hoy usan onsubmit="return confirm('...')": reemplazar ese
 * atributo por data-ub-confirm="mensaje" (opcional: data-ub-titulo="...",
 * data-ub-peligro) en el propio <form> -- el listener delegado de abajo se encarga
 * del resto, sin tocar el atributo `action`/`method` del formulario.
 */
(function () {
  var ICONOS = {
    success: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
    error:   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    info:    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  };

  function contenedorToast() {
    var c = document.getElementById('ub-toast-container');
    if (!c) {
      c = document.createElement('div');
      c.id = 'ub-toast-container';
      c.setAttribute('aria-live', 'polite');
      document.body.appendChild(c);
    }
    return c;
  }

  /** Muestra un toast flotante que se autocierra. Devuelve una función para
   * cerrarlo antes de tiempo (normalmente no hace falta usarla). */
  function toast(mensaje, tipo, duracionMs) {
    tipo = ICONOS[tipo] ? tipo : 'info';
    duracionMs = duracionMs || 5000;

    var el = document.createElement('div');
    el.className = 'ub-toast ' + tipo;
    el.setAttribute('role', 'status');
    el.innerHTML =
      '<span class="ub-toast-icon">' + ICONOS[tipo] + '</span>' +
      '<span class="ub-toast-msg"></span>' +
      '<button type="button" class="ub-toast-close" aria-label="Cerrar notificación">' +
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
      '</button>' +
      '<span class="ub-toast-bar"></span>';

    el.querySelector('.ub-toast-msg').textContent = mensaje; // textContent: nunca HTML sin escapar
    el.querySelector('.ub-toast-bar').style.animationDuration = duracionMs + 'ms';

    var cerrado = false;
    var timer;
    function cerrar() {
      if (cerrado) return;
      cerrado = true;
      clearTimeout(timer);
      el.classList.add('leaving');
      setTimeout(function () { el.remove(); }, 180);
    }
    el.querySelector('.ub-toast-close').addEventListener('click', cerrar);
    timer = setTimeout(cerrar, duracionMs);

    contenedorToast().appendChild(el);
    return cerrar;
  }

  /** Modal de confirmación con botones estilizados -- reemplazo de confirm().
   * opciones: { titulo, textoOk, textoCancelar, peligro } -- devuelve una
   * Promise<boolean> (true = confirmó, false = canceló/cerró). */
  function confirmar(mensaje, opciones) {
    opciones = opciones || {};
    var titulo = opciones.titulo || 'Confirmar acción';
    var textoOk = opciones.textoOk || 'Aceptar';
    var textoCancelar = opciones.textoCancelar || 'Cancelar';
    var peligro = !!opciones.peligro;

    return new Promise(function (resolve) {
      var overlay = document.getElementById('ub-confirm-overlay');
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'ub-confirm-overlay';
        overlay.innerHTML =
          '<div class="ub-confirm-card" role="alertdialog" aria-modal="true">' +
            '<div class="ub-confirm-title"></div>' +
            '<div class="ub-confirm-msg"></div>' +
            '<div class="ub-confirm-actions">' +
              '<button type="button" class="btn btn-ghost" data-ub-cancelar></button>' +
              '<button type="button" class="btn btn-primary" data-ub-ok></button>' +
            '</div>' +
          '</div>';
        document.body.appendChild(overlay);
      }

      overlay.querySelector('.ub-confirm-title').textContent = titulo;
      overlay.querySelector('.ub-confirm-msg').textContent = mensaje;
      var btnOk = overlay.querySelector('[data-ub-ok]');
      var btnCancelar = overlay.querySelector('[data-ub-cancelar]');
      btnOk.textContent = textoOk;
      btnCancelar.textContent = textoCancelar;
      btnOk.classList.toggle('peligro', peligro);

      function terminar(resultado) {
        overlay.classList.remove('open');
        limpiar();
        resolve(resultado);
      }
      function onOk() { terminar(true); }
      function onCancelar() { terminar(false); }
      function onOverlayClick(e) { if (e.target === overlay) terminar(false); }
      function onKeydown(e) { if (e.key === 'Escape') terminar(false); }
      function limpiar() {
        btnOk.removeEventListener('click', onOk);
        btnCancelar.removeEventListener('click', onCancelar);
        overlay.removeEventListener('click', onOverlayClick);
        document.removeEventListener('keydown', onKeydown);
      }

      btnOk.addEventListener('click', onOk);
      btnCancelar.addEventListener('click', onCancelar);
      overlay.addEventListener('click', onOverlayClick);
      document.addEventListener('keydown', onKeydown);

      requestAnimationFrame(function () {
        overlay.classList.add('open');
        btnOk.focus();
      });
    });
  }

  // Listener delegado para <form data-ub-confirm="mensaje">: intercepta el
  // submit nativo, muestra el modal, y solo reenvia el formulario si el
  // usuario confirma -- un solo mecanismo para todos los formularios con
  // confirmacion del sistema (ver plantillas que antes usaban
  // onsubmit="return confirm(...)"). El flag data-ub-confirmado evita el
  // loop infinito: requestSubmit() vuelve a disparar 'submit', así que la
  // segunda vez se deja pasar.
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    var mensaje = form.getAttribute('data-ub-confirm');
    if (!mensaje) return;
    if (form.dataset.ubConfirmado === '1') {
      delete form.dataset.ubConfirmado;
      return;
    }
    e.preventDefault();

    // loading.js escucha este mismo evento y se registra antes (ver
    // base.html) -- ya marco el boton como "cargando"/disabled sin saber
    // que este submit se iba a cancelar. Deshacerlo aca: si el usuario
    // cancela la confirmacion, el boton no debe quedar bloqueado para
    // siempre. Si confirma, requestSubmit() dispara un 'submit' nuevo que
    // loading.js vuelve a marcar correctamente para el envio real.
    var boton = e.submitter ||
      form.querySelector('button[type="submit"], button:not([type]), input[type="submit"]');
    if (boton) {
      boton.classList.remove('is-loading');
      boton.disabled = false;
    }

    confirmar(mensaje, {
      titulo: form.getAttribute('data-ub-titulo') || undefined,
      peligro: form.hasAttribute('data-ub-peligro'),
    }).then(function (ok) {
      if (!ok) return;
      form.dataset.ubConfirmado = '1';
      if (form.requestSubmit) form.requestSubmit();
      else form.submit();
    });
  });

  window.UB = { toast: toast, confirm: confirmar };
})();
