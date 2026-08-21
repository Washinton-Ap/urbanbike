// Auto-envia el formulario de busqueda (mismo <form> que ya arma el
// querystring de filtros) tras una pausa de escritura, sin necesidad
// del boton "Buscar". Aplica a cualquier <input class="filtro-buscador">
// dentro de un <form>.
(() => {
  const RETRASO_MS = 500;
  const temporizadores = new WeakMap();

  document.addEventListener('input', (ev) => {
    const input = ev.target;
    if (!(input instanceof HTMLInputElement) || !input.classList.contains('filtro-buscador')) return;
    const form = input.closest('form');
    if (!form) return;
    clearTimeout(temporizadores.get(form));
    temporizadores.set(form, setTimeout(() => {
      if (typeof form.requestSubmit === 'function') form.requestSubmit();
      else form.submit();
    }, RETRASO_MS));
  });
})();
