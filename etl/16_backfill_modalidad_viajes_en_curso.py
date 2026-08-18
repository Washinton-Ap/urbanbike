"""
ETL paso 16 (unico uso, NO forma parte del DAG horario): backfillea
modalidad_actual='hora' e inicio_segmento_actual=fecha_inicio para los
viajes reales que ya estaban 'activo'/'pendiente_validacion' antes de
que existieran estos 2 campos (ver
docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md,
Prioridad 2 -- 3 viajes reales confirmados el 16-ago-2026). Sin esto,
vig_devolver() no tendria de donde leer la modalidad al finalizarlos.

Idempotente: solo toca viajes donde modalidad_actual todavia esta
vacio -- correrlo de nuevo no pisa nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import filter_literal, get_admin_client  # noqa: E402


def main() -> None:
    pb = get_admin_client()
    viajes = pb.list_records(
        "viajes",
        filter=f'(estado = "activo" || estado = "pendiente_validacion") && modalidad_actual = ""',
        per_page=200,
    ).get("items", [])
    print(f"{len(viajes)} viajes reales sin modalidad_actual, backfilleando...")
    for v in viajes:
        pb.update_record("viajes", v["id"], {
            "modalidad_actual": "hora",
            "inicio_segmento_actual": v.get("fecha_inicio", ""),
        })
        print(f"  {v['id']} ({v.get('bicicleta_codigo')}): modalidad_actual='hora'")
    print("Listo.")


if __name__ == "__main__":
    main()
