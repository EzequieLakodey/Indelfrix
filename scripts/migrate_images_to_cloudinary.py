"""Migra imagenes locales (static/img) a Cloudinary y actualiza la DB.

- Imagenes de la tabla `imagenes`: sube el archivo y setea url/public_id.
- Assets de UI (header, background, favicon): sube con public_id fijo.
Idempotente (overwrite=True).

Uso:
  .venv/bin/python scripts/migrate_images_to_cloudinary.py --dry-run
  .venv/bin/python scripts/migrate_images_to_cloudinary.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cloudinary  # noqa: E402
import cloudinary.uploader  # noqa: E402

from app import app, db, Imagen, _cloudinary_ready  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(BASE, 'static', 'img')
DRY = '--dry-run' in sys.argv

ASSETS_UI = [
    ('header.webp', 'header'),
    ('background.webp', 'background'),
    ('favicon.webp', 'favicon'),
]


def subir(path, public_id, folder):
    res = cloudinary.uploader.upload(
        path, folder=folder, public_id=public_id, overwrite=True, resource_type='image'
    )
    return res['secure_url'], res['public_id']


def main():
    if not _cloudinary_ready():
        print('ERROR: Cloudinary no configurado (falta CLOUDINARY_URL)')
        sys.exit(1)
    print('modo:', 'DRY-RUN' if DRY else 'REAL')

    with app.app_context():
        pendientes = Imagen.query.filter(~Imagen.url.like('http%')).all()
        print(f'imagenes locales en DB: {len(pendientes)}')
        for img in pendientes:
            path = os.path.join(IMG_DIR, img.url)
            if not os.path.isfile(path):
                print(f'  [FALTA] id={img.id_imagen} {img.url!r}')
                continue
            if DRY:
                print(f'  [subiria] id={img.id_imagen} {img.url!r} -> migracion_{img.id_imagen}')
                continue
            url, pid = subir(path, f'migracion_{img.id_imagen}', 'indelfrix/imagenes')
            img.url = url
            img.public_id = pid
            print(f'  id={img.id_imagen} -> {pid}')

        print('assets UI:')
        for nombre, pid in ASSETS_UI:
            path = os.path.join(IMG_DIR, nombre)
            if not os.path.isfile(path):
                print(f'  [FALTA] {nombre}')
                continue
            if DRY:
                print(f'  [subiria] {nombre} -> indelfrix/static/{pid}')
                continue
            url, _ = subir(path, pid, 'indelfrix/static')
            print(f'  {nombre} -> {url}')

        if not DRY:
            db.session.commit()
            print('COMMIT OK')
        else:
            print('(dry-run: no se cambio nada)')


if __name__ == '__main__':
    main()
