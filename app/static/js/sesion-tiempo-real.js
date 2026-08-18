/* Sondeo en tiempo real (ver docs/Requerimientos_Mejoras_UrbanBike.md,
 * puntos 6 y 13): mismo timer de 4s para dos cosas independientes que
 * comparten el mismo endpoint GET /auth/estado-sesion (app/routers/auth.py) --
 * un solo sondeo, no uno por funcionalidad:
 *
 *   1. Cierre de sesion en tiempo real: cuando un admin cierra la sesion de
 *      un usuario conectado (o elimina su cuenta) desde /admin/usuarios,
 *      este script lo detecta sin esperar a que el usuario haga clic o
 *      navegue, y muestra el toast correspondiente antes de mandarlo a login.
 *   2. Contador de la campana de notificaciones (ver
 *      campana-notificaciones.js): la respuesta ya trae
 *      notificaciones_no_leidas, asi que se actualiza el badge de una vez,
 *      sin un timer aparte.
 *
 * Depende de notificaciones.js (UB.toast).
 */
(function () {
  if (!window.UB || !document.body.hasAttribute('data-sesion-activa')) return;

  var INTERVALO_MS = 4000;

  var temporizador = setInterval(function () {
    fetch('/auth/estado-sesion', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.activo) {
          clearInterval(temporizador);
          if (data.cerrada_por_admin) {
            UB.toast('El administrador ' + data.cerrada_por_admin + ' cerró tu sesión.', 'info', 5000);
            setTimeout(function () { window.location.href = '/auth/login'; }, 5000);
          } else {
            window.location.href = '/auth/login';
          }
          return;
        }
        if (window.UB_ACTUALIZAR_CAMPANA && typeof data.notificaciones_no_leidas === 'number') {
          window.UB_ACTUALIZAR_CAMPANA(data.notificaciones_no_leidas);
        }
      })
      .catch(function () { /* red caida: se reintenta en el proximo ciclo */ });
  }, INTERVALO_MS);
})();
