from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from datetime import datetime

app = Flask(__name__)

# --- CONFIGURACIÓN DE BASE DE DATOS (Para el contador) ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///indelfrix.db'
db = SQLAlchemy(app)

# --- CONFIGURACIÓN DE FLASK-MABIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'indelfrix.ventas@gmail.com'
# OJO: Aquí no va tu contraseña normal de Gmail, sino una "Contraseña de Aplicación"
app.config['MAIL_PASSWORD'] = 'hrrb irdw qgpy ongg'
app.config['MAIL_DEFAULT_SENDER'] = 'indelfrix.ventas@gmail.com'

mail = Mail(app)

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

categorias_subcategorias=db.Table('categorias_subcategorias',
    db.Column('id_categoria', db.Integer, db.ForeignKey('categorias.id_categoria'), primary_key=True),
    db.Column('id_subcategoria', db.Integer, db.ForeignKey('subcategorias.id_subcategoria'), primary_key=True)
)

class Categoria(db.Model):
    __tablename__ = 'categorias'  # <--- ESTO ES CLAVE: vincula con tu tabla de DBeaver
    id_categoria = db.Column(db.Integer, primary_key=True)
    nombre = db.Column('nombre', db.String(100), nullable=False) # Si en la DB la columna se llama 'categoria'
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
    
    # Relación muchos a muchos
    imagenes = db.relationship('Imagen', secondary=subcategorias_imagenes, backref='subcategorias')


class Imagen(db.Model):
    __tablename__ = 'imagenes'    # <--- Vincula con tu tabla 'imagenes'
    id_imagen = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(200), nullable=False)

# --- RUTAS ---
@app.route('/')
def inicio():
    # Consultamos todas las categorías y sus imágenes asociadas
    categorias_db = Categoria.query.all()
    subcategorias_db = Subcategoria.query.all()
    return render_template('index.html', categorias=categorias_db, subcategorias=subcategorias_db)

@app.route('/enviar_mail', methods=['POST'])
def enviar_mail():
    if request.method == 'POST':
        # 1. Capturar los datos del formulario
        nombre = request.form.get('nombre')
        apellido = request.form.get('apellido')
        cuit = request.form.get('cuit', 'No especificado')
        razon_social = request.form.get('razon_social', 'No especificada')
        email_usuario = request.form.get('email_usuario')
        asunto_form = request.form.get('asunto')
        detalles = request.form.get('detalles')
        telefono = request.form.get('telefono', 'No especificado')

        # 2. Guardar en DB para generar el número secuencial
        nueva_solicitud = Solicitud(tipo=asunto_form)
        db.session.add(nueva_solicitud)
        db.session.commit()

        # 3. Formatear los datos para el Asunto
        numero_solicitud = f"{nueva_solicitud.id:05d}" # Convierte 1 en 00001
        fecha_actual = datetime.now().strftime("%d/%m/%Y") # Ej: 27/03/2026
        
        # Resultado ej: "Solicitud Presupuesto #00001 ~ 27/03/2026 ~ Juan Gonzalez"
        asunto_final = f"{asunto_form} #{numero_solicitud} ~ {fecha_actual} ~ {nombre} {apellido}"

        # 4. Construir el cuerpo del mail
        cuerpo_mail = f"""
        NUEVA CONSULTA DESDE LA WEB DE INDELFRIX:
        -----------------------------------------
        DATOS DEL CLIENTE:
        - Nombre y Apellido: {nombre} {apellido}
        - Email: {email_usuario}
        - CUIT: {cuit}
        - Razón Social: {razon_social}
        - Teléfono: {telefono}
        
        DETALLES:
        {detalles}
        """

        # 5. Configurar y enviar el mensaje
        msg = Message(
            subject=asunto_final,
            recipients=['indelfrix.ventas@gmail.com'], # Destinatario (Tú)
            body=cuerpo_mail,
            reply_to=email_usuario # Si le das a "Responder", le llega al cliente
        )

        # Adjuntar archivo si el cliente subió uno
        archivo = request.files.get('archivo_adjunto')
        if archivo and archivo.filename != '':
            msg.attach(archivo.filename, archivo.content_type, archivo.read())

        try:
            mail.send(msg)
            return "¡Mensaje enviado con éxito! Nos contactaremos a la brevedad."
        except Exception as e:
            return f"Hubo un error al enviar el correo: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)