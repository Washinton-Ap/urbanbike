/* Persiste y aplica el tema claro/oscuro en localStorage. */

(function () {
  const KEY = "ub-theme";
  const root = document.documentElement;

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    localStorage.setItem(KEY, theme);
    // Actualizar ícono del botón
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.innerHTML = theme === "dark"
      ? `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"
           fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
           <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/>
           <line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
           <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/>
           <line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
           <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`
      : `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"
           fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
           <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
  }

  // Aplicar al cargar (antes de pintar para evitar flash)
  const saved = localStorage.getItem(KEY)
    || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  apply(saved);

  // Exponer toggle y set globales
  window.toggleTheme = function () {
    apply(root.getAttribute("data-theme") === "dark" ? "light" : "dark");
  };
  window.setTheme = apply;

  // Conectar botón cuando el DOM esté listo
  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("theme-toggle");
    if (btn) {
      apply(localStorage.getItem(KEY) || saved); // re-apply para actualizar ícono
      btn.addEventListener("click", window.toggleTheme);
    }
  });
})();
