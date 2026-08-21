// Muestra una vista previa de la imagen (o el nombre del PDF) recien
// seleccionada en un <input type="file">, antes de enviar el formulario.
// Uso: <input type="file" data-preview="mi-contenedor-id"> +
//      <div id="mi-contenedor-id"></div> en algun lugar cercano.
document.addEventListener('change', (ev) => {
  const input = ev.target;
  if (!(input instanceof HTMLInputElement) || input.type !== 'file' || !input.dataset.preview) return;
  const contenedor = document.getElementById(input.dataset.preview);
  if (!contenedor) return;
  const archivo = input.files && input.files[0];
  if (!archivo) {
    contenedor.innerHTML = '';
    return;
  }
  if (archivo.type === 'application/pdf') {
    contenedor.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;font-size:0.82rem;color:var(--text);padding:8px 10px;border:1px solid var(--border);border-radius:8px;">' +
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>' +
      '<span></span></div>';
    // archivo.name es controlado por el usuario (nombre real de su archivo
    // local) -- se asigna via textContent, nunca concatenado al HTML, para
    // no abrir un vector de self-XSS si el nombre contiene marcado.
    contenedor.querySelector('span').textContent = archivo.name;
    return;
  }
  if (!archivo.type.startsWith('image/')) {
    contenedor.innerHTML = '';
    return;
  }
  const lector = new FileReader();
  lector.onload = (e) => {
    contenedor.innerHTML =
      '<img src="' + e.target.result + '" style="max-width:160px;max-height:120px;border-radius:8px;border:1px solid var(--border);object-fit:cover;">';
  };
  lector.readAsDataURL(archivo);
});
