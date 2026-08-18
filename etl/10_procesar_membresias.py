"""
ETL paso 10: procesa las renovaciones de membresia que vencen (ver
docs/HOJA_DE_RUTA.md, diseno de membresias aprobado 11-ago-2026).

Reutiliza el mismo camino real de cobro que la pantalla manual del
ciclista (/ciclista/membresia): app.db.membresias_repo.procesar_vencidas_hoy()
llama internamente a la misma funcion privada (_registrar_periodo) que
usa membresias_repo.activar() -- no hay dos implementaciones del cobro
simulado, una para el boton y otra para Airflow.

Por que "diariamente" sin ser un DAG aparte con schedule propio: se
agrega como 4to paso del MISMO DAG horario que ya existe
(urbanbike_etl_hourly). Es correcto correrlo cada hora en vez de una
vez al dia porque es naturalmente idempotente -- procesar_vencidas_hoy()
solo actua sobre membresias cuya fila mas reciente sigue diciendo
'activa' con fecha_fin < hoy. En cuanto se procesa una (se renueva o se
marca vencida), su fila mas reciente deja de cumplir esa condicion, asi
que las corridas siguientes ese mismo dia no la vuelven a tocar. No
hace falta ninguna guarda de "ya corri hoy" aparte.

Sin fondos simulados (metodos_pago sin fila activa para el usuario):
la membresia se marca 'vencida' sin cobrar nada, nunca se fuerza la
renovacion -- ver membresias_repo.procesar_vencidas_hoy().
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from app.db import membresias_repo  # noqa: E402
from _snapshot import guardar_parquet  # noqa: E402


def main() -> None:
    resultado = membresias_repo.procesar_vencidas_hoy()
    print(
        f"membresias vencidas hoy: {resultado['revisadas']} revisadas, "
        f"{resultado['renovadas']} renovadas, "
        f"{resultado['marcadas_vencidas']} marcadas vencidas (sin metodo de pago valido)"
    )
    guardar_parquet(
        "terminado", "membresias_procesadas",
        [[resultado["revisadas"], resultado["renovadas"], resultado["marcadas_vencidas"]]],
        ["revisadas", "renovadas", "marcadas_vencidas"],
    )

    # Aviso anticipado de vencimiento (ver docs/HOJA_DE_RUTA.md seccion 69):
    # mismo DAG horario, 5to paso -- se corre siempre despues de procesar
    # vencidas para no avisar "por vencer" a una membresia que este mismo
    # ciclo ya se proceso como vencida.
    aviso = membresias_repo.procesar_por_vencer_hoy()
    print(
        f"membresias por vencer (<= {membresias_repo.DIAS_AVISO_VENCIMIENTO} dias): "
        f"{aviso['revisadas']} revisadas, {aviso['avisadas']} avisadas, "
        f"{aviso['sin_cuenta_real']} sin cuenta real de PocketBase"
    )
    guardar_parquet(
        "terminado", "membresias_por_vencer",
        [[aviso["revisadas"], aviso["avisadas"], aviso["sin_cuenta_real"]]],
        ["revisadas", "avisadas", "sin_cuenta_real"],
    )


if __name__ == "__main__":
    main()
