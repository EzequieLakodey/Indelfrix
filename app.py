from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from datetime import datetime
from dotenv import load_dotenv
from functools import wraps
from sqlalchemy import inspect, text
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
from zoneinfo import ZoneInfo
import os
import json
import socket
import threading
import base64
import requests
import cloudinary
import cloudinary.uploader
import time
import collections

load_dotenv()
cloudinary.reset_config()  # recarga CLOUDINARY_URL / claves luego de dotenv

# Ninguna operación de red puede colgar el worker para siempre (SMTP/SMTP bloqueado
# en Render free, Neon despertando, etc.). Falla rápida después de 20s y el
# worker sigue vivo para las próximas requests.
socket.setdefaulttimeout(20)
cloudinary.config(secure=True)

FICHA_EDITOR_EMAIL = os.getenv('FICHA_EDITOR_EMAIL', 'indelfrix.ventas@gmail.com').strip().lower()

app = Flask(__name__)
import sys
sys.modules['app'] = sys.modules[__name__]
app.secret_key = os.getenv('FLASK_SECRET', 'dev-secret')
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25 MB para fichas técnicas PDF
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config['GOOGLE_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET')

oauth = OAuth(app)
if os.getenv('GOOGLE_CLIENT_ID') and os.getenv('GOOGLE_CLIENT_SECRET'):
    oauth.register(
        name='google',
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )

# --- CONFIGURACIÓN DE BASE DE DATOS ---
# Prioriza PostgreSQL (producción, via DATABASE_URL de Render/Neon) y cae a SQLite local.
# Render entrega URLs con prefijo "postgres://" y SQLAlchemy requiere "postgresql://".
_db_url = os.environ.get('DATABASE_URL', '')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
# psycopg2 no tiene timeout de conexión por defecto: si el endpoint de Neon está
# dormido, el worker de gunicorn quedaría colgado para siempre. Fallá rápido (10s).
if _db_url.startswith('postgresql') and 'connect_timeout' not in _db_url:
    sep = '&' if '?' in _db_url else '?'
    _db_url = f'{_db_url}{sep}connect_timeout=10'
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url or 'sqlite:///indelfrix.db'
db = SQLAlchemy(app)

FICHAS_DIR = os.path.join(app.instance_path, 'fichas')
os.makedirs(FICHAS_DIR, exist_ok=True)

# --- CONFIGURACIÓN DE FLASK-MAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'indelfrix.ventas@gmail.com')

mail = Mail(app)


def _enviar_email(destinatario, asunto, cuerpo, reply_to=None, attachment=None):
    """Envía un email. Si hay BREVO_API_KEY usa la API HTTP de Brevo (puerto 443,
    funciona en Render free que bloquea SMTP); si no, cae a Flask-Mail/SMTP (Gmail),
    útil en desarrollo local.

    attachment: tupla (filename, content_bytes, mimetype) o None.
    """
    brevo_key = os.environ.get('BREVO_API_KEY', '').strip()
    remitente = os.environ.get('MAIL_USERNAME') or 'indelfrix.ventas@gmail.com'
    if brevo_key:
        payload = {
            'sender': {'email': remitente, 'name': 'Indelfrix Web'},
            'to': [{'email': destinatario}],
            'subject': asunto,
            'textContent': cuerpo,
        }
        if reply_to:
            payload['replyTo'] = {'email': reply_to}
        if attachment:
            payload['attachment'] = [{
                'name': attachment[0],
                'content': base64.b64encode(attachment[1]).decode('ascii'),
            }]
        resp = requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={'api-key': brevo_key, 'Content-Type': 'application/json'},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        return
    # Fallback SMTP (Gmail) — desarrollo local
    msg = Message(subject=asunto, recipients=[destinatario], body=cuerpo, reply_to=reply_to)
    if attachment:
        msg.attach(attachment[0], attachment[2], attachment[1])
    mail.send(msg)


def enviar_mail_async(destinatario, asunto, cuerpo, reply_to=None, attachment=None):
    """Envía un email en background sin bloquear la respuesta HTTP.

    Render free = 1 worker: si el envío cuelga (SMTP bloqueado o lento), el sitio
    entero se congela. Con esto la respuesta sale al instante y el error (si hay)
    queda en los logs sin afectar al usuario ni al sitio.
    """
    def _job():
        with app.app_context():
            try:
                _enviar_email(destinatario, asunto, cuerpo, reply_to=reply_to, attachment=attachment)
            except Exception:
                app.logger.exception('Error al enviar email en background')
    threading.Thread(target=_job, daemon=True).start()

# --- ANTI-SPAM: rate limiting in-memory (por IP, ventana 60s, máx 3 envíos) ---
_contact_timestamps = collections.defaultdict(collections.deque)
CONTACT_RATE_LIMIT = 3      # máximo de envíos
CONTACT_RATE_WINDOW = 60    # segundos


def _is_rate_limited(ip):
    """Retorna True si la IP superó el límite de envíos en la ventana."""
    now = time.time()
    dq = _contact_timestamps[ip]
    while dq and dq[0] < now - CONTACT_RATE_WINDOW:
        dq.popleft()
    if len(dq) >= CONTACT_RATE_LIMIT:
        return True
    dq.append(now)
    return False


# --- MODELO DE DATOS ---
class Solicitud(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50))
    fecha = db.Column(db.DateTime, default=datetime.now(datetime.now().astimezone().tzinfo)) # Guarda la fecha con zona horaria local

# 1. Definimos las tablas intermedias PRIMERO
# Nota: Los nombres en ForeignKey deben ser los nombres REALES de las tablas en la DB ('categorias', 'imagenes')
categorias_imagenes = db.Table('categorias_imagenes',
    db.Column('id_categoria', db.Integer, db.ForeignKey('categorias.id_categoria'), primary_key=True),
    db.Column('id_imagen', db.Integer, db.ForeignKey('imagenes.id_imagen'), primary_key=True)
)

subcategorias_imagenes = db.Table('subcategorias_imagenes',
    db.Column('id_subcategoria', db.Integer, db.ForeignKey('subcategorias.id_subcategoria'), primary_key=True),
    db.Column('id_imagen', db.Integer, db.ForeignKey('imagenes.id_imagen'), primary_key=True)
)

categorias_subcategorias = db.Table('categorias_subcategorias',
    db.Column('id_categoria', db.Integer, db.ForeignKey('categorias.id_categoria'), primary_key=True),
    db.Column('id_subcategoria', db.Integer, db.ForeignKey('subcategorias.id_subcategoria'), primary_key=True)
)

productos_imagenes = db.Table('productos_imagenes',
    db.Column('id_producto', db.Integer, db.ForeignKey('productos.id_producto'), primary_key=True),
    db.Column('id_imagen', db.Integer, db.ForeignKey('imagenes.id_imagen'), primary_key=True)
)

subcategorias_tags = db.Table('subcategorias_tags',
    db.Column('id_subcategoria', db.Integer, db.ForeignKey('subcategorias.id_subcategoria'), primary_key=True),
    db.Column('id_tag', db.Integer, db.ForeignKey('tags.id_tag'), primary_key=True)
)

class Categoria(db.Model):
    __tablename__ = 'categorias' 
    id_categoria = db.Column(db.Integer, primary_key=True)
    nombre = db.Column('nombre', db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    
    # Relación muchos a muchos
    imagenes = db.relationship('Imagen', secondary=categorias_imagenes, backref='categorias')
    # Agrega esta línea para que las solapas funcionen:
    subcategorias = db.relationship('Subcategoria', secondary=categorias_subcategorias, backref='categorias')
    
class Subcategoria(db.Model):
    __tablename__ = 'subcategorias'  # <--- Vincula con tu tabla 'subcategorias'
    id_subcategoria = db.Column(db.Integer, primary_key=True)
    nombre = db.Column('nombre', db.String(100), nullable=False) # Si en la DB la columna se llama 'subcategoria'
    descripcion = db.Column(db.Text)
    ficha_tecnica_url = db.Column(db.String(500))
    ficha_tecnica_public_id = db.Column(db.String(255))

    # Relación muchos a muchos
    imagenes = db.relationship('Imagen', secondary=subcategorias_imagenes, backref='subcategorias')
    tags = db.relationship('Tag', secondary=subcategorias_tags, backref='subcategorias')
    productos = db.relationship('Producto', backref='subcategoria', lazy=True, cascade='all, delete-orphan')

    def tiene_ficha(self):
        return bool(self.ficha_tecnica_url)

    def ficha_public_url(self):
        if not self.ficha_tecnica_url:
            return None
        return url_for('ficha_tecnica', sub_id=self.id_subcategoria)


class Imagen(db.Model):
    __tablename__ = 'imagenes'    # <--- Vincula con tu tabla 'imagenes'
    id_imagen = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), nullable=False)
    public_id = db.Column(db.String(255), nullable=True)


class Tag(db.Model):
    __tablename__ = 'tags'
    id_tag = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    color = db.Column(db.String(20))  # hex ej: '#0d6efd' (opcional, por defecto gris)


class Producto(db.Model):
    __tablename__ = 'productos'
    id_producto = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    id_subcategoria = db.Column(db.Integer, db.ForeignKey('subcategorias.id_subcategoria'), nullable=False)
    imagenes = db.relationship('Imagen', secondary=productos_imagenes, backref='productos')


class Cliente(db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(200), nullable=False)
    nombre = db.Column(db.String(200))
    picture = db.Column(db.String(500))
    creado = db.Column(db.DateTime, default=datetime.utcnow)


class Pedido(db.Model):
    __tablename__ = 'pedidos'
    id = db.Column(db.Integer, primary_key=True)
    id_cliente = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='abierto')
    nombre_contacto = db.Column(db.String(200))
    telefono = db.Column(db.String(50))
    empresa = db.Column(db.String(200))
    localidad = db.Column(db.String(200))
    observaciones = db.Column(db.Text)
    mail_enviado = db.Column(db.Boolean, default=False)
    whatsapp_enviado = db.Column(db.Boolean, default=False)
    whatsapp_error = db.Column(db.String(500))
    creado = db.Column(db.DateTime, default=datetime.utcnow)
    enviado_at = db.Column(db.DateTime)
    cliente = db.relationship('Cliente', backref='pedidos')
    items = db.relationship('PedidoItem', backref='pedido', cascade='all, delete-orphan', lazy=True)


class PedidoItem(db.Model):
    __tablename__ = 'pedido_items'
    id = db.Column(db.Integer, primary_key=True)
    id_pedido = db.Column(db.Integer, db.ForeignKey('pedidos.id'), nullable=False)
    id_producto = db.Column(db.Integer, db.ForeignKey('productos.id_producto'), nullable=True)
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    nombre = db.Column(db.String(200), nullable=False)
    categoria = db.Column(db.String(100))
    subcategoria = db.Column(db.String(100))

# --- RUTAS ---
@app.template_filter('fecha_ar')
def _fecha_hora_ar(dt):
    """Filtro Jinja: formatea fecha/hora UTC al horario de Argentina (ej: 11/09/2026 14:32)."""
    if not dt:
        return ''
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo('UTC'))
    return dt.astimezone(ZoneInfo('America/Argentina/Buenos_Aires')).strftime('%d/%m/%Y %H:%M')


@app.route('/')
def inicio():
    # Consultamos todas las categorías y sus imágenes asociadas
    categorias_db = Categoria.query.all()
    subcategorias_db = Subcategoria.query.all()
    tags_db = Tag.query.order_by(Tag.nombre).all()

    # Filtro server-side por tag (?tag=<id>): solo subcategorías que tengan ese tag
    tag_id = request.args.get('tag', type=int)
    tag_activo = db.session.get(Tag, tag_id) if tag_id else None
    categorias_vista = []
    for cat in categorias_db:
        if tag_activo:
            subs = [s for s in cat.subcategorias if tag_activo in s.tags]
        else:
            subs = list(cat.subcategorias)
        if subs:
            categorias_vista.append({'cat': cat, 'subs': subs})

    # Pasamos el año actual para el footer
    current_year = datetime.now().year
    return render_template('index.html', categorias=categorias_db, subcategorias=subcategorias_db,
                           categorias_vista=categorias_vista, tags=tags_db, tag_activo=tag_activo,
                           current_year=current_year)


def _ensure_schema():
    db.create_all()
    inspector = inspect(db.engine)
    if 'subcategorias' in inspector.get_table_names():
        cols = {col['name'] for col in inspector.get_columns('subcategorias')}
        statements = []
        if 'ficha_tecnica_url' not in cols:
            statements.append('ALTER TABLE subcategorias ADD COLUMN ficha_tecnica_url VARCHAR(500)')
        if 'ficha_tecnica_public_id' not in cols:
            statements.append('ALTER TABLE subcategorias ADD COLUMN ficha_tecnica_public_id VARCHAR(255)')
        for stmt in statements:
            db.session.execute(text(stmt))
        if statements:
            db.session.commit()
    if 'imagenes' in inspector.get_table_names():
        cols = {col['name'] for col in inspector.get_columns('imagenes')}
        if 'public_id' not in cols:
            db.session.execute(text('ALTER TABLE imagenes ADD COLUMN public_id VARCHAR(255)'))
            db.session.commit()
    if 'productos' in inspector.get_table_names():
        cols = {col['name'] for col in inspector.get_columns('productos')}
        if 'nombre' not in cols:
            db.session.execute(text("ALTER TABLE productos ADD COLUMN nombre VARCHAR(200) DEFAULT ''"))
            db.session.commit()
    if 'pedidos' in inspector.get_table_names():
        cols = {col['name'] for col in inspector.get_columns('pedidos')}
        if 'localidad' not in cols:
            db.session.execute(text("ALTER TABLE pedidos ADD COLUMN localidad VARCHAR(200)"))
            db.session.commit()


def _cloudinary_ready():
    cfg = cloudinary.config()
    return bool(cfg.cloud_name and cfg.api_key and cfg.api_secret)


ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp'}


def _is_image(file_storage):
    if not file_storage or not file_storage.filename:
        return False
    ext = os.path.splitext(file_storage.filename)[1].lower()
    return ext in ALLOWED_IMAGE_EXTENSIONS


def upload_imagen(file_storage, folder='indelfrix/imagenes', entity_type='general', entity_id=None):
    if not _cloudinary_ready():
        filename = secure_filename(file_storage.filename)
        path = os.path.join(app.static_folder, 'img', filename)
        file_storage.save(path)
        return {'url': filename, 'public_id': None}
    public_id = f'{entity_type}_{entity_id}_{secure_filename(os.path.splitext(file_storage.filename)[0])}' if entity_id else None
    result = cloudinary.uploader.upload(
        file_storage,
        folder=folder,
        public_id=public_id,
        resource_type='image',
        overwrite=True if public_id else False,
    )
    return {'url': result.get('secure_url'), 'public_id': result.get('public_id')}


def delete_imagen(imagen):
    if imagen.public_id and _cloudinary_ready():
        try:
            cloudinary.uploader.destroy(imagen.public_id, resource_type='image')
        except Exception:
            pass
    elif imagen.url and not imagen.url.startswith('http'):
        path = os.path.join(app.static_folder, 'img', imagen.url)
        if os.path.isfile(path):
            os.remove(path)


def procesar_imagenes(files, entity, entity_type):
    """Sube imágenes válidas de un input file y las agrega a la relación .imagenes del entity."""
    for archivo in files:
        if archivo and archivo.filename and _is_image(archivo):
            resultado = upload_imagen(archivo, entity_type=entity_type, entity_id=getattr(entity, f'id_{entity_type}', None) or entity.id)
            img = Imagen(url=resultado['url'], public_id=resultado['public_id'])
            entity.imagenes.append(img)


def eliminar_imagenes_seleccionadas(entity, form_eliminar_list):
    """Elimina imágenes marcadas con checkboxes en formularios de edición."""
    eliminar_ids = [int(x) for x in form_eliminar_list if x.isdigit()]
    for img in list(entity.imagenes):
        if img.id_imagen in eliminar_ids:
            delete_imagen(img)
            entity.imagenes.remove(img)
            db.session.delete(img)


def _normalize_email(value):
    return (value or '').strip().lower()


def can_edit_fichas():
    return bool(
        session.get('admin_logged_in')
        and _normalize_email(session.get('admin_email')) == FICHA_EDITOR_EMAIL
    )


def _is_pdf(file_storage):
    if not file_storage or not file_storage.filename:
        return False
    ext = os.path.splitext(file_storage.filename)[1].lower()
    return ext == '.pdf'


def delete_ficha_file(sub):
    if sub.ficha_tecnica_public_id and _cloudinary_ready():
        try:
            cloudinary.uploader.destroy(sub.ficha_tecnica_public_id, resource_type='raw')
        except Exception:
            pass
    if sub.ficha_tecnica_url and not str(sub.ficha_tecnica_url).startswith('http'):
        path = os.path.join(FICHAS_DIR, os.path.basename(sub.ficha_tecnica_url))
        if os.path.isfile(path):
            os.remove(path)
    sub.ficha_tecnica_url = None
    sub.ficha_tecnica_public_id = None


def save_ficha(sub, file_storage):
    if not _is_pdf(file_storage):
        raise ValueError('El archivo debe ser un PDF (.pdf).')
    delete_ficha_file(sub)
    if _cloudinary_ready():
        result = cloudinary.uploader.upload(
            file_storage,
            resource_type='raw',
            folder='indelfrix/fichas',
            public_id=f'subcategoria_{sub.id_subcategoria}',
            overwrite=True,
            invalidate=True,
        )
        sub.ficha_tecnica_url = result.get('secure_url')
        sub.ficha_tecnica_public_id = result.get('public_id')
        return
    filename = f'subcategoria_{sub.id_subcategoria}.pdf'
    file_storage.save(os.path.join(FICHAS_DIR, filename))
    sub.ficha_tecnica_url = filename
    sub.ficha_tecnica_public_id = None


with app.app_context():
    _ensure_schema()


# ------------------ RUTAS DE ADMIN ------------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = _normalize_email(request.form.get('email') or '')
        password = request.form.get('password') or ''
        ADMIN_PASS = os.getenv('ADMIN_PASS', 'scrypt:32768:8:1$nG6sEUJpV32UG6FQ$1923c7208fdfe049eb807f83c2d067cb5eaab2cfe4a6daa71c4360bb2145f75251ed8a711698a1b566d4c1af1f65b62a3c5f22780d63dba2ab1b1fe1f212e4ae')
        if email == FICHA_EDITOR_EMAIL and check_password_hash(ADMIN_PASS, password):
            session['admin_logged_in'] = True
            session['admin_email'] = email
            flash('Acceso concedido.', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('Credenciales inválidas', 'danger')
    return render_template('admin/login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_email', None)
    flash('Sesión cerrada', 'info')
    return redirect(url_for('inicio'))


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Debes iniciar sesión', 'warning')
            return redirect(url_for('admin_login'))
        if _normalize_email(session.get('admin_email')) != FICHA_EDITOR_EMAIL:
            flash('No tenés permisos de administrador', 'danger')
            session.clear()
            return redirect(url_for('admin_login'))
        return fn(*args, **kwargs)
    return wrapper


def google_ready():
    cid = os.getenv('GOOGLE_CLIENT_ID', '').strip()
    csecret = os.getenv('GOOGLE_CLIENT_SECRET', '').strip()
    if not cid or not csecret:
        return False
    if 'aqui' in cid.lower() or 'aqui' in csecret.lower():
        return False
    return True


def cliente_actual():
    cid = session.get('cliente_id')
    if not cid:
        return None
    return db.session.get(Cliente, cid)


def pedido_abierto(cliente):
    if not cliente:
        return None
    return Pedido.query.filter_by(id_cliente=cliente.id, estado='abierto').first()


@app.context_processor
def inject_admin_flags():
    cliente = cliente_actual()
    pedido = pedido_abierto(cliente)
    items = pedido.items if pedido else []
    return {
        'can_edit_fichas': can_edit_fichas(),
        'ficha_editor_email': FICHA_EDITOR_EMAIL,
        'admin_email': session.get('admin_email'),
        'cliente': cliente,
        'pedido_abierto_actual': pedido,
        'pedido_items': items,
        'pedido_count': sum((item.cantidad or 0) for item in items),
        'google_ready': google_ready(),
    }


def _apply_ficha_change(sub):
    archivo = request.files.get('ficha_tecnica')
    quitar = request.form.get('quitar_ficha')
    quiere_cambiar = bool((archivo and archivo.filename) or quitar)
    if not quiere_cambiar:
        return
    if not can_edit_fichas():
        raise PermissionError(
            f'Solo {FICHA_EDITOR_EMAIL} puede cargar, reemplazar o quitar fichas técnicas.'
        )
    if archivo and archivo.filename:
        save_ficha(sub, archivo)
    elif quitar:
        delete_ficha_file(sub)


@app.route('/admin')
@admin_required
def admin_dashboard():
    categorias_db = Categoria.query.all()
    subcategorias_db = Subcategoria.query.all()
    return render_template('admin/dashboard.html', categorias=categorias_db, subcategorias=subcategorias_db)

@app.route('/enviar_mail', methods=['POST'])
def enviar_mail():
    if request.method == 'POST':
        # --- Anti-spam: honeypot ---
        if request.form.get('website'):
            # Los bots rellenan el campo oculto; los humanos no lo ven.
            return "¡Mensaje enviado con éxito! Nos contactaremos a la brevedad."
        # --- Anti-spam: rate limiting ---
        if _is_rate_limited(request.remote_addr):
            return "Demasiados envíos en poco tiempo. Por favor esperá un minuto e intentá de nuevo."
        # 1. Capturar los datos del formulario
        nombre = request.form.get('nombre', '')
        email_usuario = request.form.get('email', '') # Coincide con 'name="email"'
        empresa = request.form.get('empresa', 'No especificada') # Coincide con 'name="empresa"'
        asunto_form = request.form.get('asunto', 'Consulta Web')
        detalles = request.form.get('detalles', '')
        telefono = request.form.get('telefono', 'No especificado')

        # Campos adicionales técnicos
        camara_largo = request.form.get('camara_largo', '')
        camara_ancho = request.form.get('camara_ancho', '')
        camara_alto = request.form.get('camara_alto', '')
        producto_tipo = request.form.get('producto_tipo', 'No especificado')
        frecuencia_apertura = request.form.get('frecuencia_apertura', 'No especificada')
        temp_entrada = request.form.get('temp_entrada', '')
        temp_deseada = request.form.get('temp_deseada', '')
        tiempo_objetivo = request.form.get('tiempo_objetivo', '')
        tipo_camara = request.form.get('tipo_camara', 'No especificado')
        aislacion_tipo = request.form.get('aislacion_tipo', 'No especificado')
        aislacion_espesor = request.form.get('aislacion_espesor', '')
        aislacion_densidad = request.form.get('aislacion_densidad', '')
        posee_antecamara = request.form.get('posee_antecamara', 'No especificado')
        producto_envoltorio = request.form.get('producto_envoltorio', 'No')
        tipo_envoltorio = request.form.get('tipo_envoltorio', 'No aplica')

        # Productos seleccionados desde el catálogo
        productos_seleccionados_raw = request.form.get('productos_seleccionados', '[]')
        try:
            productos_seleccionados = json.loads(productos_seleccionados_raw)
        except (json.JSONDecodeError, TypeError):
            productos_seleccionados = []

        # 2. Guardar en DB para generar el número secuencial
        nueva_solicitud = Solicitud(tipo=asunto_form)
        db.session.add(nueva_solicitud)
        db.session.commit()

        # 3. Formatear los datos para el Asunto
        numero_solicitud = f"{nueva_solicitud.id:05d}"
        fecha_actual = datetime.now().strftime("%d/%m/%Y")
        
        asunto_final = f"{asunto_form} #{numero_solicitud} ~ {fecha_actual} ~ {nombre}"

        # 4. Construir el cuerpo del mail
        cuerpo_mail = f"""
        NUEVA CONSULTA DESDE LA WEB DE INDELFRIX:
        -----------------------------------------
        DATOS DEL CLIENTE:
        - Nombre Completo: {nombre}
        - Email: {email_usuario}
        - Empresa / Razón Social: {empresa}
        - Teléfono: {telefono}
        
        DETALLES:
        {detalles}
        """

        # Agregar productos seleccionados
        if productos_seleccionados:
            cuerpo_mail += "\nPRODUCTOS CONSULTADOS:\n"
            for prod in productos_seleccionados:
                prod_nombre = prod.get('nombre', 'Sin nombre')
                prod_cantidad = prod.get('cantidad', 1)
                cat_nombre = prod.get('cat', '')
                sub_nombre = prod.get('sub', '')
                cantidad_str = f" (Cantidad: {prod_cantidad})" if prod_cantidad and int(prod_cantidad) > 1 else ""
                if cat_nombre and sub_nombre:
                    cuerpo_mail += f"- {cat_nombre} > {sub_nombre}: {prod_nombre}{cantidad_str}\n"
                elif sub_nombre:
                    cuerpo_mail += f"- {sub_nombre}: {prod_nombre}{cantidad_str}\n"
                else:
                    cuerpo_mail += f"- {prod_nombre}{cantidad_str}\n"

        # Agregar especificaciones técnicas al cuerpo del mail
        cuerpo_mail += "\nESPECIFICACIONES TÉCNICAS:\n"
        cuerpo_mail += f"- Dimensiones cámara (L x A x H m): {camara_largo or '-'} x {camara_ancho or '-'} x {camara_alto or '-'}\n"
        cuerpo_mail += f"- Tipo de producto: {producto_tipo}\n"
        cuerpo_mail += f"- Temperatura entrada (°C): {temp_entrada or '-'}\n"
        cuerpo_mail += f"- Temperatura deseada (°C): {temp_deseada or '-'}\n"
        cuerpo_mail += f"- Tiempo objetivo (horas): {tiempo_objetivo or '-'}\n"
        cuerpo_mail += f"- Tipo de cámara: {tipo_camara}\n"
        cuerpo_mail += f"- Aislación: {aislacion_tipo} — Espesor: {aislacion_espesor or '-'} mm — Densidad: {aislacion_densidad or '-'} kg/m3\n"
        cuerpo_mail += f"- Posee antecámara: {posee_antecamara}\n"
        cuerpo_mail += f"- Producto con envoltura: {producto_envoltorio}"
        if producto_envoltorio == 'Si':
            cuerpo_mail += f" — Tipo de envoltura: {tipo_envoltorio}\n"
        else:
            cuerpo_mail += "\n"
        cuerpo_mail += f"- Frecuencia apertura puertas: {frecuencia_apertura}\n"

        # 5. Armar adjunto (si el cliente subió uno) y enviar en background
        attachment = None
        archivo = request.files.get('archivo_adjunto')
        if archivo and archivo.filename != '':
            attachment = (archivo.filename, archivo.read(), archivo.content_type)

        enviar_mail_async(
            destinatario='indelfrix.ventas@gmail.com',
            asunto=asunto_final,
            cuerpo=cuerpo_mail,
            reply_to=email_usuario,  # Si le dan a "Responder", le llega al cliente
            attachment=attachment,
        )
        return "¡Mensaje enviado con éxito! Nos contactaremos a la brevedad."


# --- RUTAS CRUD (ejemplo: crear/editar/eliminar Categoría) ---
@app.route('/admin/categorias/nueva', methods=['GET', 'POST'])
@admin_required
def admin_create_categoria():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        nueva = Categoria(nombre=nombre, descripcion=descripcion)
        db.session.add(nueva)
        db.session.flush()
        procesar_imagenes(request.files.getlist('imagenes'), nueva, 'categoria')
        db.session.commit()
        flash('Categoría creada', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/create_categoria.html')


@app.route('/admin/categorias/<int:id>/editar', methods=['GET', 'POST'])
@admin_required
def admin_edit_categoria(id):
    cat = Categoria.query.get_or_404(id)
    if request.method == 'POST':
        cat.nombre = request.form.get('nombre')
        cat.descripcion = request.form.get('descripcion')
        eliminar_imagenes_seleccionadas(cat, request.form.getlist('eliminar_imagen'))
        procesar_imagenes(request.files.getlist('imagenes'), cat, 'categoria')
        db.session.commit()
        flash('Categoría actualizada', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/edit_categoria.html', categoria=cat)


@app.route('/admin/categorias/<int:id>/eliminar')
@admin_required
def admin_delete_categoria(id):
    cat = Categoria.query.get_or_404(id)
    for img in list(cat.imagenes):
        delete_imagen(img)
        db.session.delete(img)
    cat.imagenes.clear()
    cat.subcategorias.clear()
    db.session.delete(cat)
    db.session.commit()
    flash('Categoría eliminada', 'info')
    return redirect(url_for('admin_dashboard'))


@app.route('/fichas/<int:sub_id>')
def ficha_tecnica(sub_id):
    sub = Subcategoria.query.get_or_404(sub_id)
    if not sub.ficha_tecnica_url:
        abort(404)
    download_name = f"{secure_filename(sub.nombre) or 'ficha'}.pdf"
    if str(sub.ficha_tecnica_url).startswith('http'):
        return redirect(sub.ficha_tecnica_url)
    filename = os.path.basename(sub.ficha_tecnica_url)
    return send_from_directory(
        FICHAS_DIR,
        filename,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=download_name,
    )


@app.route('/admin/subcategorias/nueva', methods=['GET', 'POST'])
@admin_required
def admin_create_subcategoria():
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    tags = Tag.query.order_by(Tag.nombre).all()
    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        if not nombre:
            flash('El nombre es obligatorio', 'danger')
            return render_template('admin/create_subcategoria.html', categorias=categorias, tags=tags)
        nueva = Subcategoria(
            nombre=nombre,
            descripcion=request.form.get('descripcion'),
        )
        categoria_ids = request.form.getlist('categorias')
        for cat_id in categoria_ids:
            cat = Categoria.query.get(cat_id)
            if cat:
                nueva.categorias.append(cat)
        tags_sel = {int(t) for t in request.form.getlist('tags') if t.isdigit()}
        nueva.tags = [t for t in tags if t.id_tag in tags_sel]
        db.session.add(nueva)
        db.session.flush()
        procesar_imagenes(request.files.getlist('imagenes'), nueva, 'subcategoria')
        try:
            _apply_ficha_change(nueva)
        except PermissionError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return render_template('admin/create_subcategoria.html', categorias=categorias, tags=tags)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return render_template('admin/create_subcategoria.html', categorias=categorias, tags=tags)
        db.session.commit()
        flash('Subcategoría creada', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/create_subcategoria.html', categorias=categorias, tags=tags)


@app.route('/admin/subcategorias/<int:id>/editar', methods=['GET', 'POST'])
@admin_required
def admin_edit_subcategoria(id):
    sub = Subcategoria.query.get_or_404(id)
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    tags = Tag.query.order_by(Tag.nombre).all()
    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        if not nombre:
            flash('El nombre es obligatorio', 'danger')
            return render_template('admin/edit_subcategoria.html', subcategoria=sub, categorias=categorias, tags=tags)
        sub.nombre = nombre
        sub.descripcion = request.form.get('descripcion')
        seleccionadas = {int(cid) for cid in request.form.getlist('categorias') if cid.isdigit()}
        sub.categorias = [cat for cat in categorias if cat.id_categoria in seleccionadas]
        tags_sel = {int(t) for t in request.form.getlist('tags') if t.isdigit()}
        sub.tags = [t for t in tags if t.id_tag in tags_sel]
        eliminar_imagenes_seleccionadas(sub, request.form.getlist('eliminar_imagen'))
        procesar_imagenes(request.files.getlist('imagenes'), sub, 'subcategoria')
        try:
            _apply_ficha_change(sub)
        except PermissionError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return render_template('admin/edit_subcategoria.html', subcategoria=sub, categorias=categorias, tags=tags)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return render_template('admin/edit_subcategoria.html', subcategoria=sub, categorias=categorias, tags=tags)
        db.session.commit()
        flash('Subcategoría actualizada', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/edit_subcategoria.html', subcategoria=sub, categorias=categorias, tags=tags)


@app.route('/admin/subcategorias/<int:id>/eliminar')
@admin_required
def admin_delete_subcategoria(id):
    sub = Subcategoria.query.get_or_404(id)
    if sub.tiene_ficha() and not can_edit_fichas():
        flash(
            f'Solo {FICHA_EDITOR_EMAIL} puede eliminar una subcategoría que tiene ficha técnica.',
            'danger',
        )
        return redirect(url_for('admin_dashboard'))
    if sub.tiene_ficha():
        delete_ficha_file(sub)
    for img in list(sub.imagenes):
        delete_imagen(img)
        db.session.delete(img)
    sub.imagenes.clear()
    sub.categorias.clear()
    db.session.delete(sub)
    db.session.commit()
    flash('Subcategoría eliminada', 'info')
    return redirect(url_for('admin_dashboard'))


# --- RUTAS CRUD PRODUCTOS ---
@app.route('/admin/productos/nuevo', methods=['GET', 'POST'])
@admin_required
def admin_create_producto():
    subcategorias = Subcategoria.query.order_by(Subcategoria.nombre).all()
    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        id_subcategoria = request.form.get('id_subcategoria', type=int)
        if not nombre or not id_subcategoria:
            flash('Nombre y subcategoría son obligatorios', 'danger')
            return render_template('admin/create_producto.html', subcategorias=subcategorias)
        sub = Subcategoria.query.get(id_subcategoria)
        if not sub:
            flash('Subcategoría inválida', 'danger')
            return render_template('admin/create_producto.html', subcategorias=subcategorias)
        nuevo = Producto(nombre=nombre, id_subcategoria=id_subcategoria)
        db.session.add(nuevo)
        db.session.flush()
        procesar_imagenes(request.files.getlist('imagenes'), nuevo, 'producto')
        db.session.commit()
        flash('Producto creado', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/create_producto.html', subcategorias=subcategorias)


@app.route('/admin/productos/<int:id>/editar', methods=['GET', 'POST'])
@admin_required
def admin_edit_producto(id):
    prod = Producto.query.get_or_404(id)
    subcategorias = Subcategoria.query.order_by(Subcategoria.nombre).all()
    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        if not nombre:
            flash('El nombre es obligatorio', 'danger')
            return render_template('admin/edit_producto.html', producto=prod, subcategorias=subcategorias)
        prod.nombre = nombre
        prod.id_subcategoria = request.form.get('id_subcategoria', type=int) or prod.id_subcategoria
        eliminar_imagenes_seleccionadas(prod, request.form.getlist('eliminar_imagen'))
        procesar_imagenes(request.files.getlist('imagenes'), prod, 'producto')
        db.session.commit()
        flash('Producto actualizado', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/edit_producto.html', producto=prod, subcategorias=subcategorias)


@app.route('/admin/productos/<int:id>/eliminar')
@admin_required
def admin_delete_producto(id):
    prod = Producto.query.get_or_404(id)
    for img in list(prod.imagenes):
        delete_imagen(img)
        db.session.delete(img)
    db.session.delete(prod)
    db.session.commit()
    flash('Producto eliminado', 'info')
    return redirect(url_for('admin_dashboard'))


# --- RUTAS ADMIN: TAGS ---
@app.route('/admin/tags', methods=['GET', 'POST'])
@admin_required
def admin_tags():
    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        color = (request.form.get('color') or '').strip()
        if not nombre:
            flash('El nombre del tag es obligatorio', 'danger')
        elif Tag.query.filter(db.func.lower(Tag.nombre) == nombre.lower()).first():
            flash('Ya existe un tag con ese nombre', 'warning')
        else:
            db.session.add(Tag(nombre=nombre, color=color or None))
            db.session.commit()
            flash(f'Tag "{nombre}" creado', 'success')
        return redirect(url_for('admin_tags'))
    tags = Tag.query.order_by(Tag.nombre).all()
    return render_template('admin/tags.html', tags=tags)


@app.route('/admin/tags/<int:id>/editar', methods=['POST'])
@admin_required
def admin_edit_tag(id):
    tag = Tag.query.get_or_404(id)
    nombre = (request.form.get('nombre') or '').strip()
    color = (request.form.get('color') or '').strip()
    if not nombre:
        flash('El nombre no puede estar vacío', 'danger')
        return redirect(url_for('admin_tags'))
    duplicado = Tag.query.filter(
        db.func.lower(Tag.nombre) == nombre.lower(), Tag.id_tag != id
    ).first()
    if duplicado:
        flash('Ya existe otro tag con ese nombre', 'warning')
        return redirect(url_for('admin_tags'))
    tag.nombre = nombre
    tag.color = color or None
    db.session.commit()
    flash('Tag actualizado', 'success')
    return redirect(url_for('admin_tags'))


@app.route('/admin/tags/<int:id>/eliminar')
@admin_required
def admin_delete_tag(id):
    tag = Tag.query.get_or_404(id)
    db.session.delete(tag)
    db.session.commit()
    flash('Tag eliminado (se quitó de todas las subcategorías)', 'info')
    return redirect(url_for('admin_tags'))


# --- RUTAS ADMIN: PEDIDOS ---
PEDIDO_ESTADOS = ('abierto', 'enviado', 'gestionado')


@app.route('/admin/pedidos')
@admin_required
def admin_pedidos():
    estado = request.args.get('estado', '')
    query = Pedido.query.order_by(Pedido.id.desc())
    if estado in PEDIDO_ESTADOS:
        query = query.filter_by(estado=estado)
    return render_template('admin/pedidos.html', pedidos=query.all(), estado_filtro=estado)


@app.route('/admin/pedidos/<int:id>')
@admin_required
def admin_pedido_detalle(id):
    pedido = Pedido.query.get_or_404(id)
    return render_template('admin/pedido_detalle.html', pedido=pedido, estados=PEDIDO_ESTADOS)


@app.route('/admin/pedidos/<int:id>/estado', methods=['POST'])
@admin_required
def admin_pedido_estado(id):
    pedido = Pedido.query.get_or_404(id)
    nuevo = request.form.get('estado', '')
    if nuevo not in PEDIDO_ESTADOS:
        flash('Estado inválido', 'danger')
        return redirect(url_for('admin_pedido_detalle', id=id))
    pedido.estado = nuevo
    db.session.commit()
    flash(f'Pedido #{pedido.id:05d} → estado "{nuevo}"', 'success')
    return redirect(url_for('admin_pedido_detalle', id=id))


@app.route('/api/productos/<int:sub_id>')
def api_productos(sub_id):
    sub = Subcategoria.query.get_or_404(sub_id)
    productos = [{'id': p.id_producto, 'nombre': p.nombre} for p in sub.productos]
    return {'productos': productos}


import pedidos  # noqa: E402,F401  — registra login Google y rutas de pedido


if __name__ == '__main__':
    # Usar el puerto que asigne el hosting o 5000 por defecto
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False') == 'True')