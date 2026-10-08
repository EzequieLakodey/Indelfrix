"""Backup completo de la DB a JSON (sin depender de pg_dump).

Uso: .venv/bin/python scripts/backup_db.py
Salida: instance/backups/backup_YYYYmmdd_HHMMSS.json (gitignored)
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from app import app, db  # noqa: E402


def volcar_tabla(nombre):
    cols = [c['name'] for c in inspect(db.engine).get_columns(nombre)]
    filas = db.session.execute(text(f'SELECT * FROM "{nombre}"')).mappings().all()
    return [{k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in dict(f).items()} for f in filas]


def main():
    destino_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'instance', 'backups')
    os.makedirs(destino_dir, exist_ok=True)
    with app.app_context():
        tablas = inspect(db.engine).get_table_names()
        dump = {t: volcar_tabla(t) for t in tablas}
    destino = os.path.join(destino_dir, f'backup_{datetime.now():%Y%m%d_%H%M%S}.json')
    with open(destino, 'w', encoding='utf-8') as fh:
        json.dump(dump, fh, ensure_ascii=False, indent=1, default=str)
    total = sum(len(v) for v in dump.values())
    print(f'OK backup -> {destino}')
    for t in sorted(dump):
        print(f'  {t}: {len(dump[t])} filas')
    print(f'total: {total} filas')


if __name__ == '__main__':
    main()
