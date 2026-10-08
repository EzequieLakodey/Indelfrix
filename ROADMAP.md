# Roadmap — Indelfrix Web App

> Documento de referencia sobre la arquitectura, el estado actual y las especificaciones
> técnicas de la aplicación web de Indelfrix. Para tareas pendientes, ver `todo.md`.
>
> Última actualización: 08/10/2026

---

## 1. Resumen ejecutivo

Aplicación web de catálogo y consulta para **Indelfrix**, empresa de ingeniería
frigorífica (cámaras frigoríficas, condensadores, evaporadores y paneles).
Construida con **Flask** (Python) y base de datos **PostgreSQL (Neon)**, con despliegue
en **Render** (`https://indelfrix.onrender.com/` → apuntando a `indelfrix.com.ar`).

Propósito actual:

- Mostrar el catálogo de productos agrupado por **categorías → subcategorías → productos** (con especificaciones técnicas y precios exactos en ARS/USD).
- Permitir que un visitante arme un **pedido** (requiere login con Google) o envíe
  una **consulta técnica** por correo.
- Dar a un **administrador** la capacidad de gestionar el catálogo (CRUD) y las
  fichas técnicas (PDF) de cada subcategoría.

| Ítem | Valor |
|------|-------|
| Stack | Flask 2.3, Flask-SQLAlchemy 3.0, Flask-Mail 0.9, Authlib 1.3, Flask-Compress 1.25, python-dotenv |
| Base de datos | PostgreSQL vía `DATABASE_URL` (Neon) / SQLite local de respaldo (`instance/indelfrix.db`) |
| Python | 3.12.8 (fijado en `.python-version`) |
| Autenticación | Admin por sesión (email + contraseña hasheada con `werkzeug.security`) + OAuth de Google para clientes |
| Almacenamiento de medios | Cloudinary (cloud) con transformaciones automáticas (`f_auto,q_auto,w_`) |
| Notificaciones | **Pedidos → Email (Brevo API HTTP) + WhatsApp (`wa.me` con mensaje pre-armado). Consultas → solo Email.** |
| Deploy | Render (Docker / Gunicorn con 1 worker sync + compresión Brotli/Gzip) |

Política de canales de mensajería: **WhatsApp se mantiene limpio, solo pedidos**
(alta intención de compra). Las consultas generales del formulario van únicamente
a Gmail, para no mezclar ruido con oportunidades de venta.

---

## 2. Arquitectura

### 2.1 Estructura del proyecto

```
web-app/
├── app.py                 # App principal: modelos, rutas públicas, admin, email y filtro CDN
├── pedidos.py             # Login Google + flujo de pedido del cliente
├── hash_password.py       # CLI: genera el hash de la contraseña admin (ADMIN_PASS)
├── migrate_db.py          # One-shot: migra la DB SQLite local a PostgreSQL
├── requirements.txt
├── README.md
├── todo.md                # Tareas pendientes y próximos features
├── .env / .env.example    # Configuración (secretos fuera del repo)
├── templates/
│   ├── index.html         # Página pública (catálogo con lazy-load, srcset y formulario)
│   ├── pedido.html        # Checkout del pedido
│   └── admin/             # Login, dashboard, CRUD catalogo, tags y pedidos
├── static/
│   └── style.css          # Estilos globales con fondo en Cloudinary
└── instance/
    └── backups/           # Backups automáticos de base de datos (gitignored)
```

### 2.2 Modelo de datos

| Modelo | Tabla | Notas |
|--------|-------|-------|
| `Categoria` | `categorias` | Nivel superior del catálogo |
| `Subcategoria` | `subcategorias` | Pertenece a N categorías; puede tener ficha técnica PDF |
| `Producto` | `productos` | Pertenece a 1 subcategoría (incluye specs técnicas y precios) |
| `Tag` | `tags` | Propósito/uso de subcategorías (ej: "Para camiones"); N-N con `subcategorias` |
| `Imagen` | `imagenes` | Relación N-N con categorías, subcategorías y productos (almacena URL de Cloudinary y `public_id`) |
| `Cliente` | `clientes` | Usuario logueado con Google (`google_id`, `email`) |
| `Pedido` | `pedidos` | Carrito/orden del cliente (incluye `localidad`, `enviado_at`, flags y `mail_error`) |
| `PedidoItem` | `pedido_items` | Líneas del pedido (producto + cantidad + precio unitario y specs) |
| `Solicitud` | `solicitudes` | Contador para numerar las consultas del formulario |

Tablas de relación N-N: `categorias_imagenes`, `subcategorias_imagenes`,
`categorias_subcategorias`, `productos_imagenes`.

### 2.3 Flujos principales

1. **Consulta técnica (público)** — formulario en `index.html` → `POST /enviar_mail`
   → guarda `Solicitud` (número secuencial) → envía **email vía Brevo HTTP API**
   con verificación de evento (polling a la API de Brevo para confirmar entrega real)
   → adjunta archivo opcional.
2. **Pedido (cliente autenticado)** — login Google (`/login/google`) → agrega
   productos desde el catálogo (`/pedido/agregar`) → checkout (`/pedido`) →
   guarda el pedido como `enviado` → envía **email de respaldo** (con reintento y registro de `mail_error` si falla)
   → **redirige al cliente a WhatsApp** (`wa.me`) con el mensaje del pedido ya redactado.
3. **Administración** — login (`/admin/login`) validando contra
   `FICHA_EDITOR_EMAIL` + `ADMIN_PASS` (hash `werkzeug`) → CRUD completo,
   subida/borrado de imágenes en Cloudinary y gestión de fichas técnicas PDF.

---

## 3. Estado actual (Implementado)

- [x] Entorno, dependencias y carga de `.env` con `python-dotenv`.
- [x] Modelo de datos completo en PostgreSQL (Neon).
- [x] CRUD de **categorías**, **subcategorías** y **productos** con imágenes en Cloudinary.
- [x] Fichas técnicas PDF por subcategoría (`resource_type='raw'`).
- [x] Autenticación de administrador por sesión y contraseña hasheada.
- [x] **Login de cliente con Google OAuth** y validación estricta de `email_verified`.
- [x] **Flujo de pedido completo**: carrito offcanvas, checkout, email de respaldo con captura de errores (`mail_error`) y redirect a WhatsApp con fecha/hora Argentina y localidad.
- [x] Formulario de consulta técnica con honeypot antispam, rate limit por IP (3/60s), y verificación de evento Brevo en background (polling de 17s).
- [x] **Optimización de rendimiento (Fase 1)**:
  - Migración de todas las imágenes locales a Cloudinary CDN (hero, background, favicon y 33 de catálogo).
  - Filtro Jinja `|cdn` con transformaciones automáticas (`f_auto,q_auto,w_`), `srcset` responsive y `loading="lazy"`.
  - Cache HTTP estricta (`Cache-Control: public, max-age=31536000, immutable`) en `/static/` y versionado de `style.css` por `mtime`.
  - Compresión Brotli y Gzip (`Flask-Compress`) reduciendo el HTML de la home de 690 KB a ~20-31 KB (-97%).
- [x] Sistema de tags para subcategorías con badges y filtro server-side.
- [x] Panel admin de pedidos con filtros y detalle completo.
- [x] Blindaje de red (`socket.setdefaulttimeout(20)` y `connect_timeout` en Neon).

---

## 4. TO-DO & Planificación

> Las tareas pendientes, próximos features (incluyendo la **Fase 2 - Isla de Svelte** para la calculadora) y deuda técnica se gestionan de forma centralizada en el archivo **`todo.md`**.

---

## 5. Configuración de producción (Render)

Variables de entorno requeridas en el web service de Render (plantilla en `.env.example`):

| Variable | Para qué |
|----------|----------|
| `DATABASE_URL` | PostgreSQL en Neon |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Login de clientes con Google |
| `ADMIN_PASS` | Hash de la contraseña admin (`hash_password.py`) |
| `FICHA_EDITOR_EMAIL` | Única cuenta admin autorizada |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | Gmail + App Password (fallback local) |
| `BREVO_API_KEY` | Envío de mails por API HTTP en producción (supera el bloqueo SMTP de Render) |
| `MAIL_DEFAULT_SENDER` | Remitente de los mails |
| `PEDIDOS_MAIL_TO` | Casilla receptora de pedidos (respaldo) |
| `WHATSAPP_EMPRESA_NUMERO` | Número destino del redirect wa.me (ej: 5491144471684) |
| `CLOUDINARY_URL` | Credenciales Cloudinary |
| `SECRET_KEY` | Clave de sesiones Flask |

> **Python en Render**: fijado en `.python-version` (`3.12.8`). Drivers instalados: `psycopg2-binary` y `psycopg[binary]`.

---

## 6. Cómo contribuir / colaborar

1. Clonar el repositorio y configurar `.env` a partir de `.env.example`.
2. Instalar dependencias con `uv` (`uv venv --python 3.12.8 .venv && uv pip install -r requirements.txt`).
3. Ejecutar localmente con `./.venv/bin/python app.py` (puerto 5000).
4. No commitear `.env` ni `instance/`.
