/* Sondeo del hilo de soporte abierto (chat interno, ver
 * docs/Requerimientos_Mejoras_UrbanBike.md punto 12, Opción B).
 * Mismo intervalo de 4s que ya usa sesion-tiempo-real.js, pero propio:
 * ese timer solo trae un conteo para la campana, no el contenido de una
 * conversación -- este script solo corre en las páginas que tienen el
 * contenedor #chat-hilo (ciclista/soporte.html y los detalles de
 * conversación de Vigilancia/Admin).
 */
(function () {
  var hilo = document.getElementById('chat-hilo');
  if (!hilo) return;

  var INTERVALO_MS = 4000;
  var pollUrl = hilo.dataset.pollUrl;
  var soyCiclista = hilo.dataset.soyCiclista === '1';
  var ultimoId = hilo.dataset.ultimoId || '';

  function estaAlFondo() {
    return hilo.scrollHeight - hilo.scrollTop - hilo.clientHeight < 40;
  }

  function formatearFecha(iso) {
    return (iso || '').replace('T', ' ').replace('Z', '');
  }

  function pintar(items) {
    var pegado = estaAlFondo();
    hilo.innerHTML = '';
    if (!items.length) {
      hilo.innerHTML = '<div class="chat-vacio">Todavía no hay mensajes en esta conversación.</div>';
      ultimoId = '';
      return;
    }
    items.forEach(function (m) {
      var esPropio = (m.autor_rol === 'ciclista') === soyCiclista;
      var div = document.createElement('div');
      div.className = 'chat-msg ' + (esPropio ? 'chat-msg-propio' : 'chat-msg-otro');
      div.innerHTML =
        '<div class="chat-msg-autor"></div>' +
        '<div class="chat-msg-burbuja"></div>' +
        '<div class="chat-msg-fecha"></div>';
      div.querySelector('.chat-msg-autor').textContent = m.autor_nombre || '—';
      div.querySelector('.chat-msg-burbuja').textContent = m.texto || '';
      div.querySelector('.chat-msg-fecha').textContent = formatearFecha(m.fecha);
      hilo.appendChild(div);
    });
    ultimoId = items[items.length - 1].id;
    if (pegado) hilo.scrollTop = hilo.scrollHeight;
  }

  setInterval(function () {
    fetch(pollUrl, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var items = data.items || [];
        var idNuevo = items.length ? items[items.length - 1].id : '';
        var cambioCantidad = items.length !== hilo.querySelectorAll('.chat-msg').length;
        if (idNuevo !== ultimoId || cambioCantidad) pintar(items);
      })
      .catch(function () { /* red caída: se reintenta en el próximo ciclo */ });
  }, INTERVALO_MS);

  hilo.scrollTop = hilo.scrollHeight;
})();
