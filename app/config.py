"""Carga variables de entorno y expone un singleton `settings`."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    clickhouse_host:      str = os.getenv("CLICKHOUSE_HOST",      "localhost")
    clickhouse_http_port: int = int(os.getenv("CLICKHOUSE_HTTP_PORT", 8123))
    clickhouse_user:      str = os.getenv("CLICKHOUSE_USER",      "default")
    clickhouse_password:  str = os.getenv("CLICKHOUSE_PASSWORD",  "")
    clickhouse_db:        str = os.getenv("CLICKHOUSE_DB",        "urbanbike")

    pb_url:               str = os.getenv("PB_URL",               "http://localhost:8090")
    pb_superuser_email:   str = os.getenv("PB_SUPERUSER_EMAIL",   "")
    pb_superuser_password:str = os.getenv("PB_SUPERUSER_PASSWORD","")

    # SMTP real para correos transaccionales (código de verificación del
    # registro público). Sin default inseguro pero SIN fallar el arranque
    # -- a diferencia de SECRET_KEY, el envío de correo es best-effort
    # (ver app/email_client.py): si falta, el registro público sigue
    # funcionando, solo no llega el correo. Genérico (funciona igual con
    # Gmail o Brevo, solo cambian los valores reales en .env).
    smtp_host:         str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port:         int = int(os.getenv("SMTP_PORT", 587))
    smtp_user:         str = os.getenv("SMTP_USER", "")
    smtp_app_password: str = os.getenv("SMTP_APP_PASSWORD", "")
    smtp_from_name:    str = os.getenv("SMTP_FROM_NAME", "UrbanBike")
    # Brevo: el usuario SMTP (SMTP_USER) es un identificador de la cuenta,
    # no un remitente real -- el "From" tiene que ser un remitente
    # verificado en Brevo, que puede ser distinto. Con Gmail, en cambio,
    # el remitente SIEMPRE es la misma cuenta que autentica, así que el
    # default cae en smtp_user si no se define aparte.
    smtp_from_email:   str = os.getenv("SMTP_FROM_EMAIL", "") or os.getenv("SMTP_USER", "")

    # Correo de soporte mostrado en /auth/bloqueado (cualquier rol bloqueado,
    # además del contacto específico que ya existe ahí: pagos pendientes
    # para ciclista, gerente/admin real para empleados), en el pie de
    # factura y en las pantallas de soporte del ciclista. Deliberadamente
    # DISTINTO de smtp_from_email -- ese es el remitente del correo
    # transaccional ("no respondas a este mensaje", ver
    # app/email_client.py), sistemasoftwaredev@gmail.com, no una casilla
    # real de soporte. Bug real corregido el 16-ago-2026 (ver
    # docs/HOJA_DE_RUTA.md sección 68): este default había quedado
    # apuntando al mismo correo transaccional por error, contradiciendo
    # este mismo comentario -- si vuelve a "arreglarse" sin querer,
    # cualquier valor igual a smtp_from_email es del transaccional, no del
    # soporte real, sin importar qué diga el .env en ese momento.
    support_email: str = os.getenv("SUPPORT_EMAIL", "soporte@urbanbike.com")

    # Sin default inseguro: si SECRET_KEY no esta seteada, la app debe
    # fallar al arrancar (ver docs/HOJA_DE_RUTA.md, auditoria de
    # seguridad) en vez de firmar sesiones con un secreto conocido
    # publicamente ("dev-secret-change-me").
    _secret_key_env = os.getenv("SECRET_KEY")
    if not _secret_key_env:
        raise RuntimeError(
            "Falta la variable de entorno SECRET_KEY. Definela en tu .env "
            "(ver .env.example) antes de arrancar la aplicación -- ya no "
            "existe un valor por defecto."
        )
    secret_key: str = _secret_key_env

    # "production" activa el flag Secure de la cookie de sesion (ver
    # app/main.py); cualquier otro valor (o ausencia) se trata como
    # desarrollo local, donde no siempre hay HTTPS disponible.
    environment:   str  = os.getenv("ENVIRONMENT", "development")
    is_production: bool = environment.lower() == "production"


settings = Settings()
