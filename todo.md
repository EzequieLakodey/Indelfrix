# TO-DO & Features Pendientes — Indelfrix

> Lista de tareas pendientes, deuda técnica y próximas iteraciones de desarrollo para el proyecto Indelfrix.

---

## 🔴 Bloqueantes / Urgentes (Lanzamiento & Operación)

1. **Configurar dominio propio en Render (`indelfrix.com.ar`):**
   - Apuntar las DNS del dominio hacia Render (CNAME / registros A provistos por Render).
   - Verificar certificado SSL automático y redirección HTTP → HTTPS.
2. **Configurar UptimeRobot para el dominio propio:**
   - Crear monitor HTTP(s) en UptimeRobot apuntando a `https://indelfrix.com.ar/` cada 5 minutos.
   - Evita la suspensión de Neon DB y asegura monitoreo activo.

---

## 🟡 Fase 2 — Mejoras de Interactividad y Frontend

3. **Isla de Svelte para la Calculadora:**
   - Migrar la calculadora de cámaras frigoríficas (`calculadora.html`) a un componente autónomo de Svelte.
   - Toolchain: Vite + `@sveltejs/vite-plugin-svelte` compilando a `static/svelte/calculadora.js`.
   - Montaje limpio en el template con props iniciales inyectadas por Jinja.

---

## 🟢 Próximas Funcionalidades (Corto / Mediano Plazo)

4. **Panel Admin de Clientes y Solicitudes:**
   - Listado y detalle de las consultas técnicas enviadas desde el formulario web (`Solicitud`).
   - Listado de clientes logueados con Google.
5. **CRUD de Imágenes Independiente:**
   - Gestionar la librería de imágenes de Cloudinary en una sección propia del admin (no solo embebidas por producto/subcategoría).
6. **Acceso al Admin en UI Pública:**
   - Botón o enlace sutil en el navbar (visible únicamente cuando la sesión activa coincide con `FICHA_EDITOR_EMAIL`).
7. **Aviso de Privacidad / Términos:**
   - Aviso básico de protección de datos personales (Ley 25.326 de Argentina) en login y checkout.
8. **SEO y Analytics:**
   - Datos estructurados Schema.org (`Organization`, `Product`, `BreadcrumbList`).
   - Integración de analytics liviano.

---

## 🔵 Deuda Técnica y Robustez (Largo Plazo)

9. **Migraciones con Flask-Migrate / Alembic:**
   - Reemplazar el `_ensure_schema` automático por migraciones explícitas.
   - Limpiar columnas legacy de `pedidos` (`whatsapp_enviado`, `whatsapp_error`).
10. **Tests Automatizados:**
    - Tests unitarios y de integración para rutas críticas (catálogo, carrito, checkout, mail).
    - Actualizar stack a Flask 3.x para compatibilidad con Werkzeug/TestClient moderno.
11. **Logging Estructurado y Manejo de Errores:**
    - Estandarizar niveles de log y reemplazar bloques `except Exception:` silenciosos.
12. **Seguridad Avanzada (CSRF y Rate Limiter):**
    - Implementar CSRF (Flask-WTF) en formularios POST.
    - Reemplazar el rate limiter in-memory del formulario por Flask-Limiter o Redis (evita crecimiento indefinido de memoria).
13. **Paginación y Búsqueda:**
    - Agregar buscador de texto y paginación en el catálogo si el volumen de productos escala.
14. **Panel de Cliente:**
    - Historial de pedidos y estado para los usuarios autenticados con Google.
15. **Revisión de Canales:**
    - Evaluar rendimiento y ruido del botón flotante de WhatsApp.
