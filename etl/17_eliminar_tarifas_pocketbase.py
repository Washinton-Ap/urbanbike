"""
ETL paso 17 (unico uso, NO forma parte del DAG horario): elimina la
coleccion vieja de PocketBase 'tarifas' (tipo_bicicleta/tipo_usuario/
precio_hora, sin categoria ni dia/semana) -- reemplazada por completo
por urbanbike_operativa.tarifas (ClickHouse), ver
docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md.

Correr SOLO despues de confirmar (grep real de app/) que ningun codigo
vivo la referencia -- ver Task 11, Step 1 del plan.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402


def main() -> None:
    pb = get_admin_client()
    existentes = pb._get("/api/collections", params={"perPage": 200}).get("items", [])
    coleccion = next((c for c in existentes if c["name"] == "tarifas"), None)
    if not coleccion:
        print("tarifas: ya no existe, sin cambios.")
        return
    pb._session.delete(f"{pb.base_url}/api/collections/{coleccion['id']}").raise_for_status()
    print("tarifas: eliminada.")


if __name__ == "__main__":
    main()
