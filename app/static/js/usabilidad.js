/* Panel de usabilidad: tema, tamaño de fuente, contraste, marcador de línea,
   guía de enfoque y restaurar. Persiste todo en localStorage vía CSS variables/atributos. */

(function () {
  const KEYS = {
    fontSize:   "ub-font-size",
    contraste:  "ub-contraste",
    lineMarker: "ub-line-marker",
    focusGuide: "ub-focus-guide",
  };
  const BAND = 90; // mitad del alto de la franja de enfoque, en px

  const root = document.documentElement;
  let lineMarkerEl = null;
  let guideTopEl = null;
  let guideBottomEl = null;

  /* ── Tamaño de fuente ──────────────────────────────────────────────── */
  function applyFontSize(size) {
    if (size && size !== "normal") root.setAttribute("data-font-size", size);
    else root.removeAttribute("data-font-size");
    localStorage.setItem(KEYS.fontSize, size || "normal");
    document.querySelectorAll("[data-font-size-choice]").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-font-size-choice") === (size || "normal"));
    });
  }

  /* ── Contraste ─────────────────────────────────────────────────────── */
  function applyContraste(activo) {
    if (activo) root.setAttribute("data-contraste", "alto");
    else root.removeAttribute("data-contraste");
    localStorage.setItem(KEYS.contraste, activo ? "1" : "0");
    const chk = document.getElementById("a11y-contraste");
    if (chk) chk.checked = activo;
  }

  /* ── Marcador de línea ─────────────────────────────────────────────── */
  function ensureLineMarker() {
    if (!lineMarkerEl) {
      lineMarkerEl = document.createElement("div");
      lineMarkerEl.className = "a11y-line-marker";
      document.body.appendChild(lineMarkerEl);
    }
    return lineMarkerEl;
  }

  function applyLineMarker(activo) {
    ensureLineMarker().classList.toggle("active", activo);
    localStorage.setItem(KEYS.lineMarker, activo ? "1" : "0");
    const chk = document.getElementById("a11y-line-marker");
    if (chk) chk.checked = activo;
  }

  /* ── Guía de enfoque ───────────────────────────────────────────────── */
  function ensureFocusGuide() {
    if (!guideTopEl) {
      guideTopEl = document.createElement("div");
      guideTopEl.className = "a11y-focus-guide-mask a11y-focus-guide-top";
      guideBottomEl = document.createElement("div");
      guideBottomEl.className = "a11y-focus-guide-mask a11y-focus-guide-bottom";
      document.body.appendChild(guideTopEl);
      document.body.appendChild(guideBottomEl);
    }
  }

  function applyFocusGuide(activo) {
    ensureFocusGuide();
    guideTopEl.classList.toggle("active", activo);
    guideBottomEl.classList.toggle("active", activo);
    localStorage.setItem(KEYS.focusGuide, activo ? "1" : "0");
    const chk = document.getElementById("a11y-focus-guide");
    if (chk) chk.checked = activo;
  }

  function onMouseMove(e) {
    const y = e.clientY;
    if (lineMarkerEl && lineMarkerEl.classList.contains("active")) {
      lineMarkerEl.style.top = (y - 17) + "px";
    }
    if (guideTopEl && guideTopEl.classList.contains("active")) {
      const topH = Math.max(0, y - BAND);
      guideTopEl.style.height = topH + "px";
      guideBottomEl.style.top = (y + BAND) + "px";
      guideBottomEl.style.height = Math.max(0, window.innerHeight - (y + BAND)) + "px";
    }
  }
  document.addEventListener("mousemove", onMouseMove);

  /* ── Tema (delegado a theme.js) ────────────────────────────────────── */
  function applyTema(theme) {
    if (window.setTheme) window.setTheme(theme);
    document.querySelectorAll("[data-tema-choice]").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-tema-choice") === theme);
    });
  }

  /* ── Restaurar ─────────────────────────────────────────────────────── */
  function restaurar() {
    applyFontSize("normal");
    applyContraste(false);
    applyLineMarker(false);
    applyFocusGuide(false);
    const sysTheme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    applyTema(sysTheme);
  }

  /* ── Cargar valores guardados ──────────────────────────────────────── */
  function cargarEstadoInicial() {
    applyFontSize(localStorage.getItem(KEYS.fontSize) || "normal");
    applyContraste(localStorage.getItem(KEYS.contraste) === "1");
    applyLineMarker(localStorage.getItem(KEYS.lineMarker) === "1");
    applyFocusGuide(localStorage.getItem(KEYS.focusGuide) === "1");
    document.querySelectorAll("[data-tema-choice]").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-tema-choice") === root.getAttribute("data-theme"));
    });
  }

  /* ── Conectar UI ───────────────────────────────────────────────────── */
  document.addEventListener("DOMContentLoaded", () => {
    const toggleBtn = document.getElementById("a11y-toggle");
    const panel     = document.getElementById("a11y-panel");
    const overlay   = document.getElementById("a11y-overlay");
    const closeBtn  = document.getElementById("a11y-close");
    if (!toggleBtn || !panel) return;

    function abrir()  { panel.classList.add("open"); overlay.classList.add("open"); }
    function cerrar() { panel.classList.remove("open"); overlay.classList.remove("open"); }

    toggleBtn.addEventListener("click", abrir);
    closeBtn.addEventListener("click", cerrar);
    overlay.addEventListener("click", cerrar);

    document.querySelectorAll("[data-tema-choice]").forEach((btn) => {
      btn.addEventListener("click", () => applyTema(btn.getAttribute("data-tema-choice")));
    });
    document.querySelectorAll("[data-font-size-choice]").forEach((btn) => {
      btn.addEventListener("click", () => applyFontSize(btn.getAttribute("data-font-size-choice")));
    });

    const contrasteChk  = document.getElementById("a11y-contraste");
    const lineMarkerChk = document.getElementById("a11y-line-marker");
    const focusGuideChk = document.getElementById("a11y-focus-guide");
    if (contrasteChk)  contrasteChk.addEventListener("change",  (e) => applyContraste(e.target.checked));
    if (lineMarkerChk) lineMarkerChk.addEventListener("change", (e) => applyLineMarker(e.target.checked));
    if (focusGuideChk) focusGuideChk.addEventListener("change", (e) => applyFocusGuide(e.target.checked));

    const restoreBtn = document.getElementById("a11y-restore");
    if (restoreBtn) restoreBtn.addEventListener("click", restaurar);

    cargarEstadoInicial();
  });
})();
