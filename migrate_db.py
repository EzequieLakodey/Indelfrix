"""Migración one-shot: copia toda la base SQLite local a PostgreSQL.

Uso:
    DATABASE_URL=postgresql://user:pass@host/db python migrate_db.py

Notas:
- Lee de instance/indelfrix.db (fuente) y escribe en DATABASE_URL (destino).
- Preserva los IDs originales (las relaciones dependen de ellos).
- Al final reajusta las secuencias de Postgres para que los próximos INSERTs
  no colisionen con los IDs migrados.
- Las imágenes/PDFs no se migran: ya viven en Cloudinary; acá solo viajan
  las URLs/registros que los apuntan.
"""
import os
import sys

from sqlalchemy import create_engine, MetaData, Table, text

# Orden seguro por claves foráneas (padres primero, tablas puente al final)
TABLAS = [
    'tags',
    'categorias',
    'subcategorias',
    'imagenes',
    'productos',
    'clientes',
    'solicitud',
    'pedidos',
    'pedido_items',
    'categorias_imagenes',
    'subcategorias_imagenes',
    'categorias_subcategorias',
    'productos_imagenes',
    'subcategorias_tags',
]

# Tablas con PK entera autoincremental (para reajustar secuencias)
SECUENCIAS = {
    'tags': 'id_tag',
    'categorias': 'id_categoria',
    'subcategorias': 'id_subcategoria',
    'imagenes': 'id_imagen',
    'productos': 'id_producto',
    'clientes': 'id',
    'solicitud': 'id',
    'pedidos': 'id',
    'pedido_items': 'id',
}

SQLITE_URL = 'sqlite:///instance/indelfrix.db'

# Puentes N-N: columna FK -> tabla referenciada (para filtrar huérfanos,
# ya que SQLite no valida claves foráneas y Postgres sí)
PUENTES = {
    'categorias_imagenes': {'id_categoria': 'categorias', 'id_imagen': 'imagenes'},
    'subcategorias_imagenes': {'id_subcategoria': 'subcategorias', 'id_imagen': 'imagenes'},
    'categorias_subcategorias': {'id_categoria': 'categorias', 'id_subcategoria': 'subcategorias'},
    'productos_imagenes': {'id_producto': 'productos', 'id_imagen': 'imagenes'},
    'subcategorias_tags': {'id_subcategoria': 'subcategorias', 'id_tag': 'tags'},
}


def _ids_existentes(sconn, meta, nombre_tabla, col_pk):
    tabla = meta.tables.get(nombre_tabla)
    if tabla is None:
        return set()
    return {r[0] for r in sconn.execute(text(f'SELECT {col_pk} FROM {nombre_tabla}'))}


PKS = {
    'tags': 'id_tag',
    'categorias': 'id_categoria',
    'subcategorias': 'id_subcategoria',
    'imagenes': 'id_imagen',
    'productos': 'id_producto',
}


def main():
    dest_url = os.environ.get('DATABASE_URL', '').strip()
    if not dest_url:
        print('ERROR: definí DATABASE_URL (ej: postgresql://user:pass@host/db)')
        sys.exit(1)
    if dest_url.startswith('postgres://'):
        dest_url = dest_url.replace('postgres://', 'postgresql://', 1)
    if dest_url.startswith('sqlite'):
        print('ERROR: el destino debe ser PostgreSQL, no SQLite.')
        sys.exit(1)
    if not os.path.exists('instance/indelfrix.db'):
        print('ERROR: no se encontró instance/indelfrix.db (la fuente).')
        sys.exit(1)

    src = create_engine(SQLITE_URL)
    dst = create_engine(dest_url)

    meta_src = MetaData()
    meta_src.reflect(bind=src)

    # 1. Crear el esquema en Postgres usando los modelos de la app
    os.environ['DATABASE_URL'] = dest_url
    from app import app, db  # noqa: E402  (importar después de setear la env)
    with app.app_context():
        db.create_all()
    print('Esquema creado/verificado en destino.')

    # 2. Copiar datos tabla por tabla
    with src.connect() as sconn, dst.begin() as dconn:
        for nombre in TABLAS:
            tabla = meta_src.tables.get(nombre)
            if tabla is None:
                print(f'  {nombre}: no existe en origen, se omite')
                continue
            filas = [dict(r._mapping) for r in sconn.execute(tabla.select())]
            if not filas:
                print(f'  {nombre}: 0 filas (vacía)')
                continue
            # Filtrar filas huérfanas en tablas puente (Postgres valida FK)
            if nombre in PUENTES:
                antes = len(filas)
                for col, tabla_ref in PUENTES[nombre].items():
                    validos = _ids_existentes(sconn, meta_src, tabla_ref, PKS[tabla_ref])
                    filas = [f for f in filas if f[col] in validos]
                saltadas = antes - len(filas)
                if saltadas:
                    print(f'  {nombre}: ⚠ {saltadas} fila(s) huérfana(s) omitida(s)')
            if not filas:
                continue
            tabla_dst = Table(nombre, MetaData(), autoload_with=dst)
            dconn.execute(tabla_dst.delete())  # destino limpio (idempotente)
            dconn.execute(tabla_dst.insert(), filas)
            print(f'  {nombre}: {len(filas)} filas copiadas')

    # 3. Reajustar secuencias de Postgres para futuros INSERTs
    with dst.begin() as dconn:
        for tabla, col in SECUENCIAS.items():
            dconn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{tabla}', '{col}'), "
                f"COALESCE((SELECT MAX({col}) FROM {tabla}), 1))"
            ))
    print('Secuencias reajustadas.')
    print('MIGRACIÓN COMPLETA ✔  — verificá el catálogo con el servidor apuntando a DATABASE_URL.')


if __name__ == '__main__':
    main()
