(function () {
  function overlay() {
    let el = document.getElementById('lightbox-overlay');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'lightbox-overlay';
    el.className = 'lightbox-overlay';
    el.innerHTML =
      '<button type="button" class="lightbox-close" aria-label="Cerrar imagen ampliada">' +
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
          '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>' +
        '</svg>' +
      '</button>' +
      '<img class="lightbox-img" alt="">';
    document.body.appendChild(el);
    el.addEventListener('click', function (e) { if (e.target === el) close(); });
    el.querySelector('.lightbox-close').addEventListener('click', close);
    return el;
  }

  function open(src, alt) {
    const el = overlay();
    const img = el.querySelector('.lightbox-img');
    img.src = src;
    img.alt = alt || '';
    el.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function close() {
    const el = document.getElementById('lightbox-overlay');
    if (!el) return;
    el.classList.remove('open');
    document.body.style.overflow = '';
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') close();
  });

  // Delegacion: funciona con imagenes ya presentes en el DOM y con las
  // que se insertan despues por JS (catalogo, previews de edicion, etc.),
  // sin necesidad de volver a "escanear" la pagina.
  document.addEventListener('click', function (e) {
    const img = e.target.closest('img[data-lightbox]');
    if (!img) return;
    open(img.getAttribute('data-full') || img.src, img.alt);
  });

  window.UrbanBikeLightbox = { open: open, close: close };
})();
