#!/usr/bin/env python3
"""
Genera el diagrama entidad relacion de una base de ClickHouse.

ClickHouse no guarda claves foraneas, asi que las relaciones se deducen
por convencion de nombres: una columna id_<algo> apunta a la tabla <algo>
o a su plural. El resultado es un archivo Mermaid que se puede abrir en
https://mermaid.live o incrustar en Markdown, y un resumen en texto.

Uso:
    python erd_clickhouse.py --db urbanbike_operativa --salida erd.mmd
    python erd_clickhouse.py --host localhost --puerto 8123 --db urbanbike_operativa

Requiere: pip install requests
"""
import argparse
import json
import re
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

# Excepciones de la convencion: columna -> tabla destino
EXCEPCIONES = {
    'id_modelo': 'modelos_bicicleta',
    'id_marca': 'marcas',
    'id_categoria': 'categorias',
    'id_bicicleta': 'bicicletas',
    'id_estacion': 'estaciones',
    'id_estacion_inicio': 'estaciones',
    'id_estacion_fin': 'estaciones',
    'id_usuario': 'usuarios',
    'id_inspector': 'usuarios',
    'id_tecnico': 'usuarios',
    'id_actor': 'usuarios',
    'id_registra': 'usuarios',
    'id_verificador': 'usuarios',
    'id_alquiler': 'alquileres',
    'id_tarifa': 'tarifas',
    'id_promocion': 'promociones',
    'id_metodo_pago': 'metodos_pago',
    'id_garantia': 'garantias',
    'id_factura': 'facturas',
    'id_repuesto': 'repuestos',
    'id_orden': 'ordenes_mantenimiento',
    'id_orden_generada': 'ordenes_mantenimiento',
    'id_plan': 'planes_mantenimiento',
    'id_programado': 'mantenimientos_programados',
    'id_inspeccion': 'inspecciones',
    'id_item': 'checklist_items',
}


ARGS = None


def consultar(host, puerto, usuario, clave, sql):
    # Modo docker: ejecuta clickhouse-client dentro de un contenedor ya corriendo
    if ARGS and ARGS.docker:
        import subprocess
        cmd = ['docker', 'exec', '-i', ARGS.docker, 'clickhouse-client',
               '--query', sql, '--format', 'JSONCompact']
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[:400])
        return json.loads(r.stdout)['data']
    # Modo binario local: util para probar sin servidor levantado
    if ARGS and ARGS.binario:
        import subprocess
        cmd = [ARGS.binario, 'local']
        if ARGS.ruta_local:
            cmd += ['--path', ARGS.ruta_local]
        cmd += ['--query', sql, '--format', 'JSONCompact']
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[:400])
        return json.loads(r.stdout)['data']
    # Modo HTTP: el habitual contra ClickHouse en Docker con puerto expuesto
    params = {'query': sql, 'default_format': 'JSONCompact'}
    if usuario:
        params['user'] = usuario
    if clave:
        params['password'] = clave
    url = f'http://{host}:{puerto}/?' + urlencode(params)
    with urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))['data']


def tipo_corto(t):
    t = re.sub(r'LowCardinality\((.*?)\)', r'\1', t)
    t = re.sub(r'Nullable\((.*?)\)', r'\1', t)
    return t.replace('(', '_').replace(')', '').replace(',', '_').replace(' ', '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='localhost')
    ap.add_argument('--puerto', default='8123')
    ap.add_argument('--usuario', default='default')
    ap.add_argument('--clave', default='')
    ap.add_argument('--db', required=True)
    ap.add_argument('--salida', default='erd.mmd')
    ap.add_argument('--solo-relacionadas', action='store_true',
                    help='omite en el diagrama las tablas sin ninguna relacion')
    ap.add_argument('--binario', default='',
                    help='ruta al binario clickhouse para modo local sin servidor')
    ap.add_argument('--ruta-local', default='',
                    help='carpeta de datos para el modo binario local')
    ap.add_argument('--docker', default='',
                    help='nombre del contenedor Docker donde corre ClickHouse')
    a = ap.parse_args()
    global ARGS
    ARGS = a

    cols = consultar(a.host, a.puerto, a.usuario, a.clave, f"""
        SELECT table, name, type, position
        FROM system.columns
        WHERE database = '{a.db}'
        ORDER BY table, position
    """)
    if not cols:
        print(f'No se encontraron columnas en la base {a.db}', file=sys.stderr)
        sys.exit(1)

    tablas_info = consultar(a.host, a.puerto, a.usuario, a.clave, f"""
        SELECT name, engine, sorting_key
        FROM system.tables
        WHERE database = '{a.db}'
        ORDER BY name
    """)
    motor = {t[0]: t[1] for t in tablas_info}
    orden = {t[0]: t[2] for t in tablas_info}

    tablas = {}
    for tabla, col, tipo, _ in cols:
        tablas.setdefault(tabla, []).append((col, tipo))

    # Deducir relaciones
    relaciones = []
    for tabla, columnas in tablas.items():
        for col, _ in columnas:
            if not col.startswith('id_'):
                continue
            destino = EXCEPCIONES.get(col)
            if not destino:
                base = col[3:]
                for cand in (base, base + 's', base + 'es'):
                    if cand in tablas:
                        destino = cand
                        break
            if destino and destino in tablas and destino != tabla:
                relaciones.append((destino, tabla, col))

    con_relacion = {t for r in relaciones for t in (r[0], r[1])}

    # Mermaid
    out = ['erDiagram']
    for tabla in sorted(tablas):
        if a.solo_relacionadas and tabla not in con_relacion:
            continue
        out.append(f'    {tabla} {{')
        for col, tipo in tablas[tabla]:
            marca = ''
            if col == 'id':
                marca = ' PK'
            elif col.startswith('id_') and any(r[2] == col and r[1] == tabla for r in relaciones):
                marca = ' FK'
            out.append(f'        {tipo_corto(tipo)} {col}{marca}')
        out.append('    }')
    for destino, origen, col in sorted(set(relaciones)):
        out.append(f'    {destino} ||--o{{ {origen} : "{col}"')

    with open(a.salida, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')

    # Resumen por consola
    print(f'Base de datos: {a.db}')
    print(f'Tablas: {len(tablas)}   Relaciones deducidas: {len(set(relaciones))}')
    print()
    print(f'{"TABLA":<30} {"MOTOR":<22} {"COLS":>5}  CLAVE DE ORDENAMIENTO')
    print('-' * 100)
    for tabla in sorted(tablas):
        print(f'{tabla:<30} {motor.get(tabla,""):<22} {len(tablas[tabla]):>5}  {orden.get(tabla,"")}')
    print()
    print(f'Diagrama Mermaid escrito en: {a.salida}')
    print('Para verlo: copia el contenido en https://mermaid.live')


if __name__ == '__main__':
    main()
