// Filtra en tiempo real las filas de una tabla según el texto ingresado,
// buscando en todas las columnas visibles (sin recargar la página).
function filtrarTabla(input, tableId) {
  const texto = input.value.trim().toLowerCase();
  const tabla = document.getElementById(tableId);
  if (!tabla) return;
  const filas = tabla.querySelectorAll('tbody > tr');
  filas.forEach(fila => {
    const contenido = fila.textContent.toLowerCase();
    fila.style.display = contenido.includes(texto) ? '' : 'none';
  });
}
