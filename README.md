# Indelfrix Web App

Instrucciones para ejecutar el proyecto Flask localmente y notas de despliegue.

Requisitos

- Python 3.10+ (recomendado 3.12)
- Virtualenv (recomendado)

Instalación y ejecución local

1. Clona el repositorio y abre la carpeta del proyecto.

2. Crea y activa un entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Instala dependencias:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

4. Variables de entorno

Crea un archivo `.env` en la raíz del proyecto con al menos las siguientes variables (ajusta los valores):

```
FLASK_APP=app.py
FLASK_ENV=development
FLASK_SECRET=una_clave_secreta_larga
ADMIN_USER=admin
ADMIN_PASS=changeme

# Cloudinary (opcional, para subir imágenes)
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# Mail (opcional, para contacto)
MAIL_USERNAME=indelfrix.ventas@gmail.com
MAIL_PASSWORD=your_app_password
```

El proyecto usa `python-dotenv` y cargará `.env` automáticamente.

5. Inicializar la base de datos SQLite (crea tablas si faltan):

```bash
source .venv/bin/activate
python - <<'PY'
from app import app, db
with app.app_context():
	db.create_all()
	print('Tablas creadas/aseguradas')
PY
```

6. Ejecutar la aplicación:

```bash
source .venv/bin/activate
flask --debug run
# o
python app.py
```

Accede a:

- Sitio público: http://127.0.0.1:5000/
- Panel admin: http://127.0.0.1:5000/admin (usa `ADMIN_USER` / `ADMIN_PASS`)

Notas operativas

- Las imágenes locales en `static/img/` pueden perderse si despliegas en Render con disco efímero. Se recomienda configurar Cloudinary y usarlo para subir/servir imágenes.
- Las credenciales sensibles deben almacenarse en variables de entorno en el servicio de despliegue (Render / Heroku / similar). No subir `.env` al repositorio.
- Si planeas dejar el sitio en producción, cambia `FLASK_ENV` y usa una `FLASK_SECRET` segura.

Despliegue en Render (pistas)

- Añade las variables de entorno desde el panel de Render (no subas `.env`).
- El directorio `instance/indelfrix.db` se mantendrá en el disco del servicio solo si tu plan lo permite; de lo contrario, usa una base de datos administrada o guarda datos en un bucket/servicio externo.

Próximos pasos implementados / pendientes

- Ya: entorno, dependencias, autenticación admin mínima y CRUD básico para `Categoria`.
- Pendiente: CRUD completo de `Subcategoria` e `Imagenes` con subida a Cloudinary; añadir botón de Admin en la UI pública.

Contacto

- Si querés que continúe implementando el CRUD de imágenes y la integración con Cloudinary, decímelo y lo hago.

