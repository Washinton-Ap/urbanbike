/* Restringe lo que se puede teclear en los campos numéricos del sistema (ver
 * docs/Requerimientos_Mejoras_UrbanBike.md, punto 1: "no basta con validar al
 * enviar el formulario, hay que restringir lo que el usuario puede teclear").
 * La validación server-side que ya existe (Luhn, 10 dígitos, rechazo de no
 * numéricos, etc.) sigue siendo la autoridad final -- esto es una capa de UX
 * encima, nunca un reemplazo.
 *
 * Uso: marcar el <input> con inputmode="numeric" (enteros: teléfono, cédula,
 * tarjeta, capacidad) o inputmode="decimal" (precio_hora, latitud, longitud).
 * Para permitir un signo "-" al inicio (coordenadas, que pueden ser
 * negativas) agregar además data-ub-signed al mismo input.
 *
 * Dos capas:
 *   1. keydown: bloquea la tecla ANTES de que se escriba (lo pedido).
 *   2. input:   red de seguridad para lo que no pasa por teclado (pegar,
 *      soltar, autocompletar) -- limpia el valor si algo no numérico se coló.
 */
(function () {
  var TECLAS_SIEMPRE_PERMITIDAS = [
    'Backspace', 'Delete', 'Tab', 'Escape', 'Enter',
    'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End',
  ];

  function modoDe(el) {
    if (!(el instanceof HTMLInputElement)) return null;
    var modo = el.getAttribute('inputmode');
    return (modo === 'numeric' || modo === 'decimal') ? modo : null;
  }

  function caracterPermitido(el, modo, char) {
    if (/^[0-9]$/.test(char)) return true;
    if (modo !== 'decimal') return false;
    if (char === '.' && el.value.indexOf('.') === -1) return true;
    if (char === '-' && el.hasAttribute('data-ub-signed') &&
        el.selectionStart === 0 && el.value.indexOf('-') === -1) return true;
    return false;
  }

  document.addEventListener('keydown', function (e) {
    var modo = modoDe(e.target);
    if (!modo) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return; // copiar/pegar/deshacer/seleccionar todo
    if (TECLAS_SIEMPRE_PERMITIDAS.indexOf(e.key) !== -1) return;
    if (e.key.length === 1 && !caracterPermitido(e.target, modo, e.key)) {
      e.preventDefault();
    }
  });

  document.addEventListener('input', function (e) {
    var modo = modoDe(e.target);
    if (!modo) return;
    var el = e.target;
    var permiteSigno = modo === 'decimal' && el.hasAttribute('data-ub-signed');
    var permiteDecimal = modo === 'decimal';
    var vistoDecimal = false;
    var original = el.value;
    var limpio = '';
    for (var i = 0; i < original.length; i++) {
      var c = original[i];
      if (c >= '0' && c <= '9') { limpio += c; continue; }
      if (c === '-' && permiteSigno && limpio === '') { limpio += c; continue; }
      if (c === '.' && permiteDecimal && !vistoDecimal) { limpio += c; vistoDecimal = true; continue; }
    }
    if (limpio === original) return;
    var posOriginal = el.selectionStart;
    el.value = limpio;
    if (typeof posOriginal === 'number') {
      var pos = Math.max(0, posOriginal - (original.length - limpio.length));
      try { el.setSelectionRange(pos, pos); } catch (err) { /* algunos tipos de input no soportan setSelectionRange */ }
    }
  });
})();
