# Roadmap — Indelfrix Web App

> Documento de referencia sobre la arquitectura, el estado actual y la evolución
> planificada de la aplicación web de Indelfrix.
>
> Última actualización: 11/09/2026

---

## 1. Resumen ejecutivo

Aplicación web de catálogo y consulta para **Indelfrix**, empresa de ingeniería
frigorífica (cámaras frigoríficas, condensadores, evaporadores y paneles).
Construida con **Flask** (Python) y base de datos **SQLite**, con despliegue
apuntado a **Render** (`https://indelfrix.onrender.com/`).

Propósito actual:

- Mostrar el catálogo de productos agrupado por **categorías → subcategorías → productos**.
- Permitir que un visitante arme un **pedido** (requiere login con Google) o envíe
  una **consulta técnica** por correo.
- Dar a un **administrador** la capacidad de gestionar el catálogo (CRUD) y las
  fichas técnicas (PDF) de cada subcategoría.

| Ítem | Valor |
|------|-------|
| Stack | Flask 2.3, Flask-SQLAlchemy 3.0, Flask-Mail 0.9, Authlib 1.3, python-dotenv |
| Base de datos | SQLite (`instance/indelfrix.db`) |
| Python | 3.10+ (recomendado 3.12) |
| Autenticación | Admin por sesión (email + contraseña hasheada) + OAuth de Google para clientes |
| Almacenamiento de medios | Cloudinary (cloud) con fallback a disco local (`static/img`) |
| Notificaciones | **Pedidos → Email (Gmail SMTP) + WhatsApp (`wa.me` con mensaje pre-armado). Consultas → solo Email (Gmail).** |
| Deploy | Render (disco efímero) |

Política de canales de mensajería: **WhatsApp se mantiene limpio, solo pedidos**
(alta intención de compra). Las consultas generales del formulario van únicamente
a Gmail, para no mezclar ruido con oportunidades de venta.

---

## 2. Arquitectura

### 2.1 Estructura del proyecto

```
web-app/
├── app.py                 # App principal: modelos, rutas públicas, admin, email
├── pedidos.py             # Login Google + flujo de pedido del cliente
├── hash_password.py       # CLI: genera el hash de la contraseña admin (ADMIN_PASS)
├── requirements.txt
├── README.md
├── .env / .env.example    # Configuración (secretos fuera del repo)
├── templates/
│   ├── index.html         # Página pública (catálogo + formulario de consulta)
│   ├── pedido.html        # Checkout del pedido
│   └── admin/             # Login, dashboard, CRUD catalogo, tags y pedidos
├── static/
│   ├── style.css
│   └── img/               # Imágenes del catálogo (fallback local)
└── instance/
    └── indelfrix.db       # SQLite (no versionado en producción)
```

### 2.2 Modelo de datos

| Modelo | Tabla | Notas |
|--------|-------|-------|
| `Categoria` | `categorias` | Nivel superior del catálogo |
| `Subcategoria` | `subcategorias` | Pertenece a N categorías; puede tener ficha técnica PDF |
| `Producto` | `productos` | Pertenece a 1 subcategoría |
| `Tag` | `tags` | Propósito/uso de subcategorías (ej: "Para camiones"); N-N con `subcategorias` |
| `Imagen` | `imagenes` | Relación N-N con categorías, subcategorías y productos |
| `Cliente` | `clientes` | Usuario logueado con Google (`google_id`, `email`) |
| `Pedido` | `pedidos` | Carrito/orden del cliente (incluye `localidad`, `enviado_at`, flags de notificación) |
| `PedidoItem` | `pedido_items` | Líneas del pedido (producto + cantidad) |
| `Solicitud` | `solicitudes` | Contador para numerar las consultas del formulario |

Tablas de relación N-N generadas: `categorias_imagenes`, `subcategorias_imagenes`,
`categorias_subcategorias`, `productos_imagenes`.

### 2.3 Flujos principales

1. **Consulta técnica (público)** — formulario en `index.html` → `POST /enviar_mail`
   → guarda `Solicitud` (genera número secuencial) → envía **solo email** con los
   datos, productos consultados y especificaciones (dimensiones, temperaturas,
   aislación, antecámara, etc.) → adjunta archivo opcional.

2. **Pedido (cliente autenticado)** — login Google (`/login/google`) → agrega
   productos desde el catálogo (`/pedido/agregar`) → checkout (`/pedido`) →
   guarda el pedido como `enviado` (con fecha/hora) → envía **email de respaldo**
   a la empresa → **redirige al cliente a WhatsApp** (`wa.me`) con el mensaje del
   pedido ya redactado. El email es la red de seguridad por si el cliente no
   completa el envío en WhatsApp.

3. **Administración** — login (`/admin/login`) validando contra
   `FICHA_EDITOR_EMAIL` + `ADMIN_PASS` (hash `werkzeug`) → CRUD de categorías,
   subcategorías y productos, con subida/borrado de imágenes (Cloudinary) y
   gestión de fichas técnicas PDF (restringida a `FICHA_EDITOR_EMAIL`).

---

## 3. Estado actual (qué ya está implementado)

- [x] Entorno, dependencias y carga de `.env` con `python-dotenv`.
- [x] Modelo de datos completo (categorías, subcategorías, productos, imágenes).
- [x] CRUD de **categorías** (crear/editar/eliminar, con imágenes).
- [x] CRUD de **subcategorías** (con selección de categorías, imágenes y ficha técnica).
- [x] CRUD de **productos** (con asignación a subcategoría e imágenes).
- [x] Fichas técnicas PDF por subcategoría (subida a Cloudinary, `resource_type='raw'`).
- [x] Autenticación de administrador por sesión.
- [x] **Contraseña admin hasheada** (`werkzeug.security`) + script `hash_password.py`.
- [x] **Login de cliente con Google OAuth configurado y funcional** (Authlib).
- [x] Validación estricta de `email_verified` en el callback de Google.
- [x] **Flujo de pedido completo**: carrito (offcanvas) → checkout → email de
      respaldo + redirect a WhatsApp (`wa.me`) con mensaje pre-armado.
- [x] **Fecha y hora (horario Argentina)** en el encabezado del pedido (mail y WhatsApp).
- [x] Campo `localidad` en el pedido + migración automática segura.
- [x] Offcanvas de pedido en el catálogo + UX de login (alerta/prompt cuando
      OAuth no está configurado en el entorno).
- [x] Navbar con icono de usuario y dropdown (email + cerrar sesión).
- [x] Formulario de consulta técnica con envío de email y adjuntos.
- [x] Integración Cloudinary (con fallback a disco local si no hay credenciales).
- [x] Subida de imágenes con validación de extensiones y `secure_filename`.
- [x] Helpers reutilizables de imágenes (`procesar_imagenes` / `eliminar_imagenes_seleccionadas`).
- [x] Notificaciones centralizadas (`notificar_pedido`).
- [x] Migración de esquema automática **no destructiva** (`_ensure_schema` con
      `ALTER TABLE ADD COLUMN`, sin `DROP TABLE`).
- [x] Botones sociales flotantes (WhatsApp, Facebook, Instagram) + footer con
      contacto clickeable (`tel:` / `mailto:`).
- [x] Despliegue en Render (`ProxyFix` para headers de proxy).
- [x] API interna `/api/productos/<sub_id>`.
- [x] **Anti-spam en el formulario de contacto**: honeypot oculto + rate limit por IP (máx. 3 envíos/60s).
- [x] Código legacy de WhatsApp Cloud API eliminado (`requests` incluida).
- [x] **Sistema de tags para subcategorías**: modelo `Tag` + N-N `subcategorias_tags`,
      CRUD en admin, asignación múltiple desde el form de subcategoría, badges en las
      cards del catálogo y filtro server-side (`?tag=<id>`).
- [x] **Panel admin de pedidos**: listado con filtro por estado, detalle completo
      (cliente, contacto, productos, observaciones) y cambio de estado
      (`abierto` → `enviado` → `gestionado`).

---

## 4. TO-DO — Pendientes y recomendaciones

### 🔴 Antes de lanzar (bloqueantes)

1. **Publicar el login de Google a producción:**
   - En Google Cloud Console: pasar la pantalla de consentimiento de "Pruebas"
     a "Producción" (sin eso, solo los usuarios de prueba pueden entrar).
   - Registrar la URI `https://indelfrix.onrender.com/login/google/callback`
     en las URIs de redirección autorizadas del cliente OAuth.
   - Configurar `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` como variables de
     entorno en Render.
2. **Migrar SQLite a PostgreSQL administrado** (Render ofrece Postgres gratuito).
   El disco de Render es efímero: **cada redeploy borra la base de datos**,
   incluyendo pedidos y clientes. Es el mayor riesgo actual del proyecto.
   Con SQLAlchemy el cambio es casi solo la URI de conexión.

### 🟡 Corto plazo (features priorizadas)

_Sección completada._ Los ítems de tags y panel de pedidos quedaron implementados
(ver §3). Restan evaluar nuevas features según feedback de uso real.

### 🟢 Mediano plazo (robustez y operación)

3. Panel admin de **clientes** y **solicitudes** (listado de consultas del formulario).
4. CRUD de **imágenes** como entidad independiente (hoy se gestionan embebidas
   en cada CRUD).
5. Botón/link de acceso al panel admin en la UI pública (visible solo con sesión admin).
6. Migraciones explícitas con **Flask-Migrate/Alembic** (reemplaza `_ensure_schema`).
7. **Tests automatizados** (unitarios + integración de rutas y flujo de pedido).
   Nota: el `test_client` actual falla por incompatibilidad Flask 2.3 / Werkzeug
   nuevo — conviene actualizar el stack a Flask 3.x como parte de este trabajo.
8. **Logging estructurado** y manejo de errores (hoy varios `except` silencian).
9. **CSRF en formularios** (Flask-WTF) y rate limiting global (Flask-Limiter).

### 🔵 Recomendaciones extra / largo plazo

10. **Aviso de privacidad básico** junto al login/checkout — la app guarda emails
    y teléfonos de clientes (Ley 25.326 de Protección de Datos, Argentina).
11. **Analytics** (p.ej. Google Analytics o alternativa liviana) para saber qué
    subcategorías se miran más + **datos estructurados Schema.org** (Organization,
    Product) para mejorar el SEO. Post-lanzamiento.
12. Paginación y búsqueda en el catálogo si crece el número de productos.
13. Cotizador automático (presupuesto en base a las especificaciones del formulario).
14. Panel de cliente (historial de pedidos y estado).
15. Reevaluar el botón flotante de WhatsApp: si empieza a traer demasiado ruido
    (consultas sueltas que ensucian el canal de pedidos), considerar quitarlo.
16. Migración del front a una SPA o SSR moderno si la complejidad lo amerita.

---

## 5. Deuda técnica y observaciones

### Resuelta ✅

- ~~Contraseña admin en texto plano~~ → hasheada con `werkzeug.security` +
  script `hash_password.py` para regenerarla.
- ~~`static/img-notused/`~~ → directorio eliminado (37 imágenes sin uso).
- ~~Duplicación de lógica de subida de imágenes~~ → refactorizada en los helpers
  `procesar_imagenes()` / `eliminar_imagenes_seleccionadas()`.
- ~~Múltiples rutas de notificación~~ → centralizadas; el código legacy de
  Cloud API ya fue eliminado por completo.

### Pendiente ⚠️

- **`FICHA_EDITOR_EMAIL` como único "rol"**: no hay modelo de permisos granular.
- **`_ensure_schema`** sigue siendo `ALTER TABLE` manual al arrancar; mejorado
  (no destructivo) pero preferir migraciones (TO-DO #6).
- **SQLite efímero en Render** — riesgo de pérdida de datos en producción
  (elevado a TO-DO #2, bloqueante de lanzamiento).
- **Sin tests** — los cambios se validan manualmente (TO-DO #7).

---

## 6. Cómo contribuir / colaborar

1. Clonar el repo y seguir las instrucciones de `README.md`.
2. Crear rama por feature (`git checkout -b feat/...`) desde `dev`.
3. Ejecutar localmente: `python app.py` (puerto 5000).
4. Validar contra `instance/indelfrix.db` local antes de subir.
5. No commitear `.env` ni `instance/` (ver `.gitignore`).
6. Para regenerar la contraseña admin: `python hash_password.py "nueva_clave"`
   y pegar el hash en `ADMIN_PASS` del `.env`.

---

*Roadmap mantenido a partir del análisis del código en
`/home/blank/Documents/Proyects/Indelfrix/web-app` (app.py, pedidos.py, templates,
static, README y git log).*
