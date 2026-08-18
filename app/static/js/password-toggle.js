(function () {
  var EYE =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
      '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>' +
    '</svg>';
  var EYE_OFF =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
      '<path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a20.3 20.3 0 0 1 4.22-5.94M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a20.3 20.3 0 0 1-2.16 3.19M14.12 14.12a3 3 0 1 1-4.24-4.24"/>' +
      '<line x1="1" y1="1" x2="23" y2="23"/>' +
    '</svg>';

  function envolver(input) {
    if (input.dataset.toggleListo) return;
    input.dataset.toggleListo = "1";

    var wrap = document.createElement("div");
    wrap.style.position = "relative";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    input.style.paddingRight = "38px";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("aria-label", "Mostrar contraseña");
    btn.tabIndex = -1;
    btn.style.cssText =
      "position:absolute;right:6px;top:50%;transform:translateY(-50%);" +
      "background:none;border:none;padding:4px;cursor:pointer;" +
      "color:var(--text-muted);display:flex;align-items:center;";
    btn.innerHTML = EYE;

    btn.addEventListener("click", function () {
      var mostrar = input.type === "password";
      input.type = mostrar ? "text" : "password";
      btn.innerHTML = mostrar ? EYE_OFF : EYE;
      btn.setAttribute("aria-label", mostrar ? "Ocultar contraseña" : "Mostrar contraseña");
    });

    wrap.appendChild(btn);
  }

  function escanear() {
    document.querySelectorAll('input[type="password"]').forEach(envolver);
  }

  document.addEventListener("DOMContentLoaded", escanear);
  // Delegacion para inputs que aparecen despues (modales abiertos con JS,
  // como el de "Crear usuario" en Admin) -- mismo patron que lightbox.js.
  document.addEventListener("click", function () {
    setTimeout(escanear, 0);
  });
})();
