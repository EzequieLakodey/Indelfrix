# Roadmap — Indelfrix Web App

> Documento de referencia sobre la arquitectura, el estado actual y la evolución
> planificada de la aplicación web de Indelfrix.
>
> Última actualización: 04/09/2026

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
| Autenticación | Admin por sesión (usuario/contraseña) + OAuth de Google para clientes |
| Almacenamiento de medios | Cloudinary (cloud) con fallback a disco local (`static/img`) |
| Notificaciones | Email (Gmail SMTP) + WhatsApp Cloud API (Meta) |
| Deploy | Render (disco efímero) |

---

## 2. Arquitectura

### 2.1 Estructura del proyecto

```
web-app/
├── app.py                 # App principal: modelos, rutas públicas, admin, email
├── pedidos.py             # Login Google + flujo de pedido del cliente
├── requirements.txt
├── README.md
├── .env / .env.example    # Configuración (secretos fuera del repo)
├── templates/
│   ├── index.html         # Página pública (catálogo + formulario de consulta)
│   ├── pedido.html        # Checkout del pedido
│   └── admin/             # Login, dashboard y CRUD (base_admin.html)
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
| `Imagen` | `imagenes` | Relación N-N con categorías, subcategorías y productos |
| `Cliente` | `clientes` | Usuario logueado con Google (`google_id`, `email`) |
| `Pedido` | `pedidos` | Carrito/orden del cliente con estado |
| `PedidoItem` | `pedido_items` | Líneas del pedido (producto + cantidad) |
| `Solicitud` | `solicitudes` | Contador para numerar las consultas del formulario |

Tablas de relación N-N generadas: `categorias_imagenes`, `subcategorias_imagenes`,
`categorias_subcategorias`, `productos_imagenes`.

### 2.3 Flujos principales

1. **Consulta técnica (público)** — formulario en `index.html` → `POST /enviar_mail`
   → guarda `Solicitud` (genera número secuencial) → envía email con los datos,
   productos consultados y especificaciones (dimensiones, temperaturas, aislación,
   antecámara, etc.) → adjunta archivo opcional.

2. **Pedido (cliente autenticado)** — login Google (`/login/google`) → agrega
   productos desde el catálogo (`/pedido/agregar`) → checkout (`/pedido`) → envía
   email interno + notificación WhatsApp (opcional).

3. **Administración** — login (`/admin/login`) validando contra
   `FICHA_EDITOR_EMAIL` + `ADMIN_PASS` → CRUD de categorías, subcategorías y
   productos, con subida/borrado de imágenes (Cloudinary) y gestión de fichas
   técnicas PDF (restringida a `FICHA_EDITOR_EMAIL`).

---

## 3. Estado actual (qué ya está implementado)

- [x] Entorno, dependencias y carga de `.env` con `python-dotenv`.
- [x] Modelo de datos completo (categorías, subcategorías, productos, imágenes).
- [x] CRUD de **categorías** (crear/editar/eliminar, con imágenes).
- [x] CRUD de **subcategorías** (con selección de categorías, imágenes y ficha técnica).
- [x] CRUD de **productos** (con asignación a subcategoría e imágenes).
- [x] Fichas técnicas PDF por subcategoría (subida a Cloudinary, con `resource_type='raw'`).
- [x] Autenticación de administrador por sesión.
- [x] Login de cliente con Google (OAuth) vía `Authlib`.
- [x] Flujo de pedido (carrito → checkout → email + WhatsApp).
- [x] Formulario de consulta técnica con envío de email y adjuntos.
- [x] Integración Cloudinary (con fallback a disco local si no hay credenciales).
- [x] Subida de imágenes con validación de extensiones y `secure_filename`.
- [x] Migración de esquema automática al arrancar (`_ensure_schema`).
- [x] Despliegue en Render (`ProxyFix` para headers de proxy).
- [x] API interna `/api/productos/<sub_id>`.

---

## 4. Estado pendiente / brecha

Marcado explícitamente como "pendiente" en el README o identificado en el código:

- [ ] **CRUD de imágenes como entidad independiente** (hoy las imágenes se gestionan
      de forma embebida en cada CRUD, no hay pantalla dedicada).
- [ ] **Botón de acceso a Admin en la UI pública** (el README lo lista como pendiente).
- [ ] **Panel de gestión de pedidos para el administrador** — los pedidos se envían
      por email/WhatsApp, pero no hay vista admin para listarlos ni cambiar estado.
- [ ] **Gestión de `clientes`** — no hay CRUD ni listado de clientes registrados.

---

## 5. Roadmap propuesto

Priorizado para cerrar las brechas y robustecer la app antes de escalar.

### Fase 1 — Completar el catálogo y la administración (corto plazo)

1. CRUD de imágenes como entidad (reemplazar la gestión embebida por un flujo único
   y reutilizable).
2. Botón/link de acceso al panel admin en la UI pública (visible solo si hay sesión).
3. Panel admin de **pedidos**: listado, detalle, cambio de estado
   (`abierto` → `enviado`), y reenvío de email/WhatsApp.

### Fase 2 — Robustez y operación (medio plazo)

4. Panel admin de **clientes** y **solicitudes** (listado de consultas del formulario).
5. Migración de base de datos explícita (Flask-Migrate/Alembic) en lugar del
   `_ensure_schema` manual.
6. Persistencia fiable en Render: mover SQLite a una base administrada (PostgreSQL)
   o a un volumen persistente; hoy el disco es efímero y se pierden datos.
7. Tests automatizados (unitarios + de integración para rutas y flujos de pedido).
8. Manejo de errores y logging estructurado (hoy varios `except` silencian el error).

### Fase 3 — Seguridad y experiencia (medio/largo plazo)

9. Hash de la contraseña admin (hoy se compara en texto plano) y CSRF en formularios
   via `Flask-WTF`.
10. Rate limiting en el formulario de contacto y en el login.
11. Paginación y búsqueda en el catálogo si crece el número de productos.
12. Internacionalización / edición de textos del front (SEO ya iniciado).

### Fase 4 — Escala y features (largo plazo, opcional)

13. Cotizador automático (presupuesto en base a las especificaciones del formulario).
14. Panel de cliente (historial de pedidos y estado).
15. Migración del front a una SPA o SSR moderno si la complejidad lo amerita.

---

## 6. Deuda técnica y observaciones

- **Contraseña admin en texto plano** comparada directamente contra `ADMIN_PASS` —
  debe hashearse.
- **`FICHA_EDITOR_EMAIL` como único "roles"**: no hay modelo de permisos granular.
- **`_ensure_schema`** hace `ALTER TABLE` manuales al arrancar; frágil, preferir
  migraciones.
- **SQLite efímero en Render** — riesgo de pérdida de datos en producción.
- **Sin tests** — los cambios se validan manualmente.
- **Duplicación de lógica de subida de imágenes** en los CRUD de categoría,
  subcategoría y producto (candidato a refactor).
- **`static/img-notused/`** contiene imágenes que ya no se usan (limpieza pendiente).
- **Múltiples rutas de notificación** (email + WhatsApp) con lógica de error
  parcial — conviene centralizar en un servicio de notificaciones.

---

## 7. Cómo contribuir / colaborar

1. Clonar el repo y seguir las instrucciones de `README.md`.
2. Crear rama por feature (`git checkout -b feat/...`).
3. Ejecutar localmente: `flask --debug run` (puerto 5000).
4. Validar contra `instance/indelfrix.db` local antes de subir.
5. No commitear `.env` ni `instance/` (ver `.gitignore`).
6. Para continuar con el CRUD de imágenes y la integración Cloudinary, ver nota de
   contacto en `README.md`.

---

*Roadmap generado a partir del análisis del código en
`/home/blank/Documents/Proyects/Indelfrix/web-app` (app.py, pedidos.py, templates,
static, README y git log).*