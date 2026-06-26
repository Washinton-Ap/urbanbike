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

    secret_key:           str = os.getenv("SECRET_KEY",           "dev-secret-change-me")


settings = Settings()
