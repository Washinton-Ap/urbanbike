/* Sondeo del hilo de soporte abierto (chat interno, punto 12 Opción B;
 * expandido punto 2.4 -- ver docs/HOJA_DE_RUTA.md secciones 68 y 85).
 * Mismo intervalo de 4s que ya usa sesion-tiempo-real.js, pero propio:
 * ese timer solo trae un conteo para la campana, no el contenido de una
 * conversación -- este script solo corre en las páginas que tienen el
 * contenedor #chat-hilo (ciclista/soporte_detalle.html y los detalles de
 * conversación de Vigilancia/Admin). También arma el selector de emoji
 * del formulario de envío, sin ninguna librería externa.
 */
(function () {
  var EMOJIS = [
    '😀', '😂', '🙂', '😉', '😍', '🤔', '😅', '😢',
    '😡', '👍', '👎', '🙏', '👏', '🎉', '🚲', '⚠️',
    '✅', '❌', '⏰', '📍', '📷', '🔧', '💳', '❤️',
  ];

  var hilo = document.getElementById('chat-hilo');
  var form = document.querySelector('.chat-form');
  var csrfInput = form ? form.querySelector('input[name="csrf_token"]') : null;
  var csrfToken = csrfInput ? csrfInput.value : '';

  function extension(nombre) {
    var i = (nombre || '').lastIndexOf('.');
    return i === -1 ? '' : nombre.slice(i + 1).toLowerCase();
  }

  function formatearFecha(iso) {
    return (iso || '').replace('T', ' ').replace('Z', '');
  }

  function crearAdjunto(m) {
    var ext = extension(m.adjunto_nombre);
    var cont = document.createElement('div');
    cont.className = 'chat-adjunto';
    if (['jpg', 'jpeg', 'png', 'gif'].indexOf(ext) !== -1) {
      var a = document.createElement('a');
      a.href = m.adjunto_url; a.target = '_blank'; a.rel = 'noopener';
      var img = document.createElement('img');
      img.src = m.adjunto_url; img.alt = 'Adjunto'; img.className = 'chat-adjunto-imagen';
      a.appendChild(img); cont.appendChild(a);
    } else if (['mp4', 'mov', 'webm'].indexOf(ext) !== -1) {
      var video = document.createElement('video');
      video.src = m.adjunto_url; video.controls = true; video.className = 'chat-adjunto-video';
      cont.appendChild(video);
    } else {
      var enlace = document.createElement('a');
      enlace.href = m.adjunto_url; enlace.target = '_blank'; enlace.rel = 'noopener';
      enlace.className = 'chat-adjunto-archivo';
      enlace.textContent = 'Ver archivo adjunto';
      cont.appendChild(enlace);
    }
    return cont;
  }

  function crearFormEliminar(mensajeId, eliminarUrlBase) {
    var f = document.createElement('form');
    f.method = 'post';
    f.action = eliminarUrlBase + '/' + mensajeId;
    f.className = 'chat-msg-eliminar-form';
    f.setAttribute('data-ub-confirm', '¿Borrar este mensaje? Dejará de verse en la conversación.');
    f.setAttribute('data-ub-peligro', '');
    var tok = document.createElement('input');
    tok.type = 'hidden'; tok.name = 'csrf_token'; tok.value = csrfToken;
    var btn = document.createElement('button');
    btn.type = 'submit'; btn.className = 'chat-msg-eliminar'; btn.title = 'Borrar mensaje';
    btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>';
    f.appendChild(tok); f.appendChild(btn);
    return f;
  }

  function crearMensaje(m, soyCiclista, propioId, eliminarUrlBase) {
    var esPropio = (m.autor_rol === 'ciclista') === soyCiclista;
    var div = document.createElement('div');
    div.className = 'chat-msg ' + (esPropio ? 'chat-msg-propio' : 'chat-msg-otro');

    var autor = document.createElement('div');
    autor.className = 'chat-msg-autor';
    autor.textContent = m.autor_nombre || '—';
    div.appendChild(autor);

    if (m.eliminado) {
      var eliminado = document.createElement('div');
      eliminado.className = 'chat-msg-burbuja chat-msg-eliminado';
      eliminado.textContent = 'Mensaje eliminado';
      div.appendChild(eliminado);
    } else {
      var burbuja = document.createElement('div');
      burbuja.className = 'chat-msg-burbuja';
      if (m.texto) {
        var texto = document.createElement('div');
        texto.className = 'chat-msg-texto';
        texto.textContent = m.texto;
        burbuja.appendChild(texto);
      }
      if (m.adjunto_url) burbuja.appendChild(crearAdjunto(m));
      div.appendChild(burbuja);

      if (m.autor_id && m.autor_id === propioId) {
        div.appendChild(crearFormEliminar(m.id, eliminarUrlBase));
      }
    }

    var fecha = document.createElement('div');
    fecha.className = 'chat-msg-fecha';
    fecha.textContent = formatearFecha(m.fecha);
    div.appendChild(fecha);

    return div;
  }

  if (hilo) {
    var INTERVALO_MS = 4000;
    var pollUrl = hilo.dataset.pollUrl;
    var soyCiclista = hilo.dataset.soyCiclista === '1';
    var propioId = hilo.dataset.propioId || '';
    var eliminarUrlBase = hilo.dataset.eliminarUrlBase || '';
    var ultimoId = hilo.dataset.ultimoId || '';

    var estaAlFondo = function () {
      return hilo.scrollHeight - hilo.scrollTop - hilo.clientHeight < 40;
    };

    var pintar = function (items) {
      var pegado = estaAlFondo();
      hilo.innerHTML = '';
      if (!items.length) {
        hilo.innerHTML = '<div class="chat-vacio">Todavía no hay mensajes en esta conversación.</div>';
        ultimoId = '';
        return;
      }
      items.forEach(function (m) {
        hilo.appendChild(crearMensaje(m, soyCiclista, propioId, eliminarUrlBase));
      });
      ultimoId = items[items.length - 1].id;
      if (pegado) hilo.scrollTop = hilo.scrollHeight;
    };

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
  }

  // ── Selector de emoji, JS puro sin librería externa (punto 2.4) ──────────
  var botonEmoji = document.getElementById('chat-btn-emoji');
  var panelEmoji = document.getElementById('chat-emoji-panel');
  var textarea = document.getElementById('chat-textarea');

  if (botonEmoji && panelEmoji && textarea) {
    EMOJIS.forEach(function (emoji) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = emoji;
      btn.addEventListener('click', function () {
        var inicio = textarea.selectionStart || textarea.value.length;
        var fin = textarea.selectionEnd || textarea.value.length;
        textarea.value = textarea.value.slice(0, inicio) + emoji + textarea.value.slice(fin);
        var cursor = inicio + emoji.length;
        textarea.setSelectionRange(cursor, cursor);
        textarea.focus();
      });
      panelEmoji.appendChild(btn);
    });

    botonEmoji.addEventListener('click', function (e) {
      e.stopPropagation();
      panelEmoji.hidden = !panelEmoji.hidden;
    });
    document.addEventListener('click', function (e) {
      if (!panelEmoji.hidden && !panelEmoji.contains(e.target) && e.target !== botonEmoji) {
        panelEmoji.hidden = true;
      }
    });
  }
})();
