from datetime import datetime
from functools import wraps
import os
import re
import threading

from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app import (
    Cliente,
    Pedido,
    PedidoItem,
    Producto,
    app,
    db,
    google_ready,
    mail,
    oauth,
    cliente_actual,
    pedido_abierto,
    _enviar_email,
    _fecha_hora_ar,
)


def _safe_next(value):
    if value and value.startswith('/') and not value.startswith('//'):
        return value
    return url_for('inicio')


def _ensure_open_pedido(cliente):
    pedido = pedido_abierto(cliente)
    if not pedido:
        pedido = Pedido(id_cliente=cliente.id, estado='abierto')
        db.session.add(pedido)
        db.session.flush()
    return pedido


def _producto_labels(producto):
    sub = producto.subcategoria
    cats = list(sub.categorias) if sub else []
    categoria = cats[0].nombre if cats else ''
    return categoria, (sub.nombre if sub else '')


def _items_payload(pedido):
    if not pedido:
        return []
    return [
        {
            'id': item.id,
            'id_producto': item.id_producto,
            'nombre': item.nombre,
            'categoria': item.categoria or '',
            'subcategoria': item.subcategoria or '',
            'cantidad': item.cantidad,
        }
        for item in pedido.items
    ]


def _pedido_texto(pedido, cliente):
    lineas = [
        f'PEDIDO WEB #{pedido.id:05d}',
        f'Fecha y hora: {_fecha_hora_ar(pedido.enviado_at)}',
        '-----------------------------------------',
        'DATOS DEL CLIENTE:',
        f'- Nombre: {pedido.nombre_contacto or cliente.nombre or "-"}',
        f'- Email (Google): {cliente.email}',
        f'- Teléfono / WhatsApp: {pedido.telefono or "-"}',
        f'- Empresa: {pedido.empresa or "-"}',
        f'- Localidad: {pedido.localidad or "-"}',
        '',
        'PRODUCTOS SOLICITADOS (sin precios ni stock):',
    ]
    for item in pedido.items:
        ruta = ' > '.join(p for p in [item.categoria, item.subcategoria] if p)
        prefix = f'{ruta}: ' if ruta else ''
        lineas.append(f'- {prefix}{item.nombre}  x{item.cantidad}')
    if pedido.observaciones:
        lineas.append('')
        lineas.append('OBSERVACIONES:')
        lineas.append(pedido.observaciones)
    lineas.append('')
    lineas.append('Contactar al cliente para presupuestar o coordinar entrega.')
    return '\n'.join(lineas)


def _pedido_whatsapp_texto(pedido, cliente):
    lineas = [
        f'Hola Indelfrix, quiero hacer el siguiente pedido (WEB #{pedido.id:05d}):',
        f'*Fecha y hora:* {_fecha_hora_ar(pedido.enviado_at)}',
        '',
        '*DATOS DE CONTACTO:*',
        f'- Nombre: {pedido.nombre_contacto or cliente.nombre or "-"}',
        f'- Email: {cliente.email}',
        f'- Teléfono: {pedido.telefono or "-"}',
        f'- Empresa: {pedido.empresa or "-"}',
        f'- Localidad: {pedido.localidad or "-"}',
        '',
        '*PRODUCTOS:*',
    ]
    for item in pedido.items:
        ruta = ' > '.join(p for p in [item.categoria, item.subcategoria] if p)
        prefix = f'{ruta}: ' if ruta else ''
        lineas.append(f'- {prefix}{item.nombre} x{item.cantidad}')
    if pedido.observaciones:
        lineas.append('')
        lineas.append('*OBSERVACIONES:*')
        lineas.append(pedido.observaciones)
    return '\n'.join(lineas)


def _url_whatsapp_empresa():
    numero = re.sub(r'\D', '', os.getenv('WHATSAPP_EMPRESA_NUMERO') or os.getenv('WHATSAPP_DESTINO') or '5491144471684')
    return f'https://wa.me/{numero}'


def _build_whatsapp_url(pedido, cliente):
    from urllib.parse import quote
    mensaje = _pedido_whatsapp_texto(pedido, cliente)
    return f"{_url_whatsapp_empresa()}?text={quote(mensaje)}"


def _send_pedido_mail(pedido, cliente, cuerpo):
    destinatario = os.getenv('PEDIDOS_MAIL_TO') or os.getenv('MAIL_USERNAME') or 'indelfrix.ventas@gmail.com'
    _enviar_email(
        destinatario=destinatario,
        asunto=f'Pedido web #{pedido.id:05d} ~ {pedido.nombre_contacto or cliente.nombre} ~ {cliente.email}',
        cuerpo=cuerpo,
        reply_to=cliente.email,
    )


def _send_pedido_mail_async(pedido_id):
    """Email de respaldo del pedido en background: no bloquea el redirect a WhatsApp.

    Re-consulta el pedido dentro del hilo (el objeto de la request está detached).
    """
    def _job():
        with app.app_context():
            pedido = db.session.get(Pedido, pedido_id)
            if not pedido:
                return
            try:
                _send_pedido_mail(pedido, pedido.cliente, _pedido_texto(pedido, pedido.cliente))
                pedido.mail_enviado = True
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                app.logger.warning('Mail de respaldo del pedido #%s falló: %s', pedido_id, exc)
    threading.Thread(target=_job, daemon=True).start()



def _agregar_producto(cliente, producto_id, cantidad):
    producto = db.session.get(Producto, producto_id)
    if not producto:
        return None, 'Producto no encontrado'
    cantidad = max(1, min(int(cantidad or 1), 9999))
    pedido = _ensure_open_pedido(cliente)
    item = next((i for i in pedido.items if i.id_producto == producto.id_producto), None)
    cat, sub = _producto_labels(producto)
    if item:
        item.cantidad = min(item.cantidad + cantidad, 9999)
        item.nombre = producto.nombre
        item.categoria = cat
        item.subcategoria = sub
    else:
        item = PedidoItem(
            pedido=pedido,
            id_producto=producto.id_producto,
            cantidad=cantidad,
            nombre=producto.nombre,
            categoria=cat,
            subcategoria=sub,
        )
        db.session.add(item)
    db.session.commit()
    return pedido, None


def cliente_required_json(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        cliente = cliente_actual()
        if not cliente:
            next_url = request.full_path if request.full_path else url_for('inicio')
            if next_url.endswith('?'):
                next_url = next_url[:-1]
            return jsonify({
                'ok': False,
                'login_required': True,
                'login_url': url_for('google_login', next=request.referrer or url_for('inicio')),
            }), 401
        return fn(*args, **kwargs)
    return wrapper


@app.route('/login/google')
def google_login():
    if not google_ready() or oauth.google is None:
        flash('El ingreso con Google todavía no está configurado.', 'warning')
        return redirect(url_for('inicio'))
    session['oauth_next'] = _safe_next(request.args.get('next'))
    add_id = request.args.get('add', type=int)
    if add_id:
        session['pending_producto_id'] = add_id
        session['pending_cantidad'] = request.args.get('cantidad', default=1, type=int)
    redirect_uri = url_for('google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route('/login/google/callback')
def google_callback():
    if not google_ready() or oauth.google is None:
        flash('El ingreso con Google todavía no está configurado.', 'warning')
        return redirect(url_for('inicio'))
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        flash('No se pudo completar el ingreso con Google. Intentá de nuevo.', 'danger')
        return redirect(url_for('inicio'))
    userinfo = token.get('userinfo') or {}
    google_id = str(userinfo.get('sub') or '')
    email = (userinfo.get('email') or '').strip().lower()
    if not google_id or not email or userinfo.get('email_verified') is not True:
        flash('Google no confirmó un email válido. Usá una cuenta de Google real.', 'danger')
        return redirect(url_for('inicio'))
    cliente = Cliente.query.filter_by(google_id=google_id).first()
    if not cliente:
        cliente = Cliente.query.filter_by(email=email).first()
    if not cliente:
        cliente = Cliente(google_id=google_id, email=email)
        db.session.add(cliente)
    cliente.google_id = google_id
    cliente.email = email
    cliente.nombre = userinfo.get('name') or cliente.nombre
    cliente.picture = userinfo.get('picture') or cliente.picture
    db.session.commit()
    session['cliente_id'] = cliente.id
    pending_id = session.pop('pending_producto_id', None)
    pending_qty = session.pop('pending_cantidad', 1)
    if pending_id:
        _agregar_producto(cliente, pending_id, pending_qty)
        flash('Ingresaste y el producto se agregó al pedido.', 'success')
    else:
        flash('Ingresaste con Google.', 'success')
    return redirect(session.pop('oauth_next', None) or url_for('inicio'))


@app.route('/logout/cliente')
def cliente_logout():
    session.pop('cliente_id', None)
    session.pop('pending_producto_id', None)
    flash('Sesión cerrada.', 'info')
    return redirect(url_for('inicio'))


@app.route('/pedido/agregar', methods=['POST'])
@cliente_required_json
def pedido_agregar():
    data = request.get_json(silent=True) or {}
    producto_id = data.get('id_producto') or request.form.get('id_producto', type=int)
    cantidad = data.get('cantidad') or request.form.get('cantidad', 1)
    try:
        producto_id = int(producto_id)
        cantidad = int(cantidad)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Datos inválidos'}), 400
    pedido, error = _agregar_producto(cliente_actual(), producto_id, cantidad)
    if error:
        return jsonify({'ok': False, 'error': error}), 404
    return jsonify({
        'ok': True,
        'count': sum(i.cantidad for i in pedido.items),
        'items': _items_payload(pedido),
    })


@app.route('/pedido/item/<int:item_id>', methods=['POST'])
@cliente_required_json
def pedido_actualizar_item(item_id):
    data = request.get_json(silent=True) or {}
    pedido = pedido_abierto(cliente_actual())
    item = next((i for i in (pedido.items if pedido else []) if i.id == item_id), None)
    if not item:
        return jsonify({'ok': False, 'error': 'Ítem no encontrado'}), 404
    if data.get('eliminar') or request.form.get('eliminar'):
        db.session.delete(item)
    else:
        try:
            item.cantidad = max(1, min(int(data.get('cantidad', item.cantidad)), 9999))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Cantidad inválida'}), 400
    db.session.commit()
    pedido = pedido_abierto(cliente_actual())
    items = _items_payload(pedido)
    return jsonify({'ok': True, 'count': sum(i['cantidad'] for i in items), 'items': items})


@app.route('/pedido', methods=['GET', 'POST'])
def pedido_checkout():
    cliente = cliente_actual()
    if not cliente:
        return redirect(url_for('google_login', next=url_for('pedido_checkout')))
    pedido = pedido_abierto(cliente)
    if request.method == 'POST':
        if not pedido or not pedido.items:
            flash('Tu pedido está vacío.', 'warning')
            return redirect(url_for('inicio') + '#catalogo')
        nombre = (request.form.get('nombre') or cliente.nombre or '').strip()
        telefono = (request.form.get('telefono') or '').strip()
        empresa = (request.form.get('empresa') or '').strip()
        localidad = (request.form.get('localidad') or '').strip()
        observaciones = (request.form.get('observaciones') or '').strip()
        if not nombre or not telefono:
            flash('Completá nombre y teléfono para que podamos contactarte.', 'danger')
            return render_template('pedido.html', pedido=pedido)
        pedido.nombre_contacto = nombre
        pedido.telefono = telefono
        pedido.empresa = empresa
        pedido.localidad = localidad
        pedido.observaciones = observaciones
        pedido.estado = 'enviado'
        pedido.enviado_at = datetime.utcnow()
        db.session.commit()
        # Email de respaldo a la empresa (red de seguridad si el cliente
        # no completa el envío en WhatsApp). El canal principal es wa.me.
        # Va en background para no bloquear el redirect.
        _send_pedido_mail_async(pedido.id)
        whatsapp_url = _build_whatsapp_url(pedido, cliente)
        return redirect(whatsapp_url)
    if not pedido or not pedido.items:
        flash('Todavía no hay productos en el pedido.', 'info')
        return redirect(url_for('inicio') + '#catalogo')
    return render_template('pedido.html', pedido=pedido)
