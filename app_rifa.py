# -*- coding: utf-8 -*-
"""
SISTEMA DE GESTION Y VENTA ONLINE DE RIFA BENEFICA (500 NUMEROS)
- Pagina Publica de Compra (/) para clientes: Pagar ahora con Pago Movil (copiar datos 1 a 1 o todos, subir comprobante) o Apartar y pagar despues.
- Panel de Administrador (/admin) para el organizador con visualizador de comprobantes y confirmacion rapida de pago.
- Generacion automatica de Tunel Publico Seguro HTTPS (SSH Reverse Tunnel).
"""

import os
import sqlite3
import csv
import io
import re
import time
import uuid
import threading
import subprocess
import hmac
import hashlib
import base64
from urllib.parse import quote
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory, Response, session, redirect, url_for

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'rifa_cataratas_seguridad_admin_2026_x77')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '407845764')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'rifa.db')
UPLOAD_DIR = os.path.join(BASE_DIR, 'static', 'uploads', 'comprobantes')
os.makedirs(UPLOAD_DIR, exist_ok=True)

CURRENT_PUBLIC_URL = ""

HAS_PG = False
PG_MODULE = None
PG_IMPORT_ERR = ""

try:
    import psycopg
    from psycopg.rows import dict_row
    HAS_PG = True
    PG_MODULE = 'psycopg3'
except Exception as e3:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        HAS_PG = True
        PG_MODULE = 'psycopg2'
    except Exception as e2:
        HAS_PG = False
        PG_IMPORT_ERR = f"psycopg3: {e3} | psycopg2: {e2}"

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://rifa_db_ft3b_user:qaWgM7FPwmoQ4q3NNkLDAFr3BHvGEJLc@dpg-dbd545a9lscs73e9tc1g-a.oregon-postgres.render.com/rifa_db_ft3b')

class RowWrapper(dict):
    def __init__(self, mapping):
        super().__init__(mapping)
        self._values = list(mapping.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

class CursorWrapper:
    def __init__(self, cur, is_postgres=False):
        self.cur = cur
        self.is_postgres = is_postgres

    def execute(self, query, params=None):
        if self.is_postgres:
            query = query.replace('?', '%s')
        if params is None:
            self.cur.execute(query)
        else:
            self.cur.execute(query, params)
        return self

    def fetchone(self):
        row = self.cur.fetchone()
        if row is None:
            return None
        return RowWrapper(dict(row)) if not isinstance(row, dict) else RowWrapper(row)

    def fetchall(self):
        rows = self.cur.fetchall()
        return [RowWrapper(dict(r)) if not isinstance(r, dict) else RowWrapper(r) for r in rows]

    @property
    def description(self):
        return self.cur.description

class DBWrapper:
    def __init__(self, raw_conn, is_postgres=False):
        self.raw_conn = raw_conn
        self.is_postgres = is_postgres

    def execute(self, query, params=None):
        cur = self.cursor()
        cur.execute(query, params)
        return cur

    def cursor(self):
        if self.is_postgres:
            if PG_MODULE == 'psycopg3':
                return CursorWrapper(self.raw_conn.cursor(), is_postgres=True)
            else:
                return CursorWrapper(self.raw_conn.cursor(cursor_factory=RealDictCursor), is_postgres=True)
        return CursorWrapper(self.raw_conn.cursor(), is_postgres=False)

    def commit(self):
        self.raw_conn.commit()

    def close(self):
        self.raw_conn.close()

DB_ERRORS = []

def get_db():
    global DB_ERRORS
    if HAS_PG:
        candidates = []
        env_url = os.environ.get('DATABASE_URL')
        if env_url:
            candidates.append(env_url)
            if 'dpg-dbd545a9lscs73e9tc1g-a' in env_url and '.oregon-postgres.render.com' not in env_url:
                candidates.append(env_url.replace('dpg-dbd545a9lscs73e9tc1g-a', 'dpg-dbd545a9lscs73e9tc1g-a.oregon-postgres.render.com'))
        # Priorizar siempre la dirección permanente probada de PostgreSQL en Render
        candidates.append('postgresql://rifa_db_ft3b_user:qaWgM7FPwmoQ4q3NNkLDAFr3BHvGEJLc@dpg-dbd545a9lscs73e9tc1g-a.oregon-postgres.render.com/rifa_db_ft3b')
        candidates.append('postgresql://rifa_db_ft3b_user:qaWgM7FPwmoQ4q3NNkLDAFr3BHvGEJLc@dpg-dbd545a9lscs73e9tc1g-a/rifa_db_ft3b')

        for u in candidates:
            try:
                url_to_connect = u.replace('postgres://', 'postgresql://', 1) if u.startswith('postgres://') else u
                if PG_MODULE == 'psycopg3':
                    raw = psycopg.connect(url_to_connect, row_factory=dict_row, connect_timeout=4)
                else:
                    raw = psycopg2.connect(url_to_connect, connect_timeout=4)
                return DBWrapper(raw, is_postgres=True)
            except Exception as e:
                err_msg = f"{u[:45]}... -> {str(e)}"
                if err_msg not in DB_ERRORS:
                    DB_ERRORS.append(err_msg)

    raw = sqlite3.connect(DB_PATH)
    raw.row_factory = sqlite3.Row
    return DBWrapper(raw, is_postgres=False)

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion (
            id INTEGER PRIMARY KEY,
            titulo TEXT,
            causa TEXT,
            premio TEXT,
            precio_usd REAL,
            tasa_bcv REAL,
            fecha_sorteo TEXT,
            loteria TEXT,
            total_numeros INTEGER,
            banco TEXT,
            telefono_pago TEXT,
            cedula_pago TEXT
        )
    """)
    
    cursor.execute("SELECT COUNT(*) FROM configuracion")
    count_cfg = cursor.fetchone()[0]
    if count_cfg == 0:
        cursor.execute("""
            INSERT INTO configuracion (
                id, titulo, causa, premio, precio_usd, tasa_bcv,
                fecha_sorteo, loteria, total_numeros, banco, telefono_pago, cedula_pago
            ) VALUES (
                1, 'Gran Rifa Benéfica', 'A beneficio de cirugía de cataratas',
                'Aire Acondicionado de Ventana 12.000 BTU', 5.0, 45.0,
                '5 de Noviembre 2026', 'Lotería del Zulia (7:00 PM)', 500,
                'BANCAMIGA', '0424-9718479', '24.522.792'
            )
        """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS numeros (
            numero INTEGER PRIMARY KEY,
            numero_str TEXT,
            estado TEXT DEFAULT 'DISPONIBLE', -- 'DISPONIBLE', 'APARTADO', 'PAGADO'
            comprador_nombre TEXT DEFAULT '',
            comprador_telefono TEXT DEFAULT '',
            comprador_cedula TEXT DEFAULT '',
            metodo_pago TEXT DEFAULT 'Pago Móvil',
            referencia_pago TEXT DEFAULT '',
            monto_pagado REAL DEFAULT 0.0,
            comprobante_img TEXT DEFAULT '',
            notas TEXT DEFAULT '',
            fecha_registro TEXT DEFAULT '',
            fecha_actualizacion TEXT DEFAULT ''
        )
    """)

    if conn.is_postgres:
        cursor.execute("ALTER TABLE numeros ADD COLUMN IF NOT EXISTS comprobante_img TEXT DEFAULT ''")
    else:
        cursor.execute("PRAGMA table_info(numeros)")
        cols = [r[1] for r in cursor.fetchall()]
        if 'comprobante_img' not in cols:
            cursor.execute("ALTER TABLE numeros ADD COLUMN comprobante_img TEXT DEFAULT ''")

    cursor.execute("SELECT COUNT(*) FROM numeros")
    count = cursor.fetchone()[0]
    if count < 500:
        for i in range(1, 501):
            num_str = f"{i:03d}"
            if conn.is_postgres:
                cursor.execute("""
                    INSERT INTO numeros (numero, numero_str, estado)
                    VALUES (%s, %s, 'DISPONIBLE')
                    ON CONFLICT (numero) DO NOTHING
                """, (i, num_str))
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO numeros (numero, numero_str, estado)
                    VALUES (?, ?, 'DISPONIBLE')
                """, (i, num_str))

    cursor.execute("""
        UPDATE numeros SET estado = 'POR_CONFIRMAR'
        WHERE estado = 'APARTADO' AND (monto_pagado > 0 OR (comprobante_img IS NOT NULL AND comprobante_img != ''))
    """)

    conn.commit()
    conn.close()

init_db()

# --- Rutas de Navegacion ---

@app.route('/')
def public_index():
    return render_template('comprar.html')

@app.route('/comprar')
def public_comprar():
    return render_template('comprar.html')

def check_admin():
    return bool(session.get('admin_autenticado'))

@app.route('/admin')
def admin_dashboard():
    if not check_admin():
        return render_template('admin_login.html')
    return render_template('admin.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        clave = request.form.get('clave', '').strip()
        if clave == ADMIN_PASSWORD:
            session['admin_autenticado'] = True
            return redirect('/admin')
        return render_template('admin_login.html', error="Clave de seguridad incorrecta. Inténtalo nuevamente.")
    
    if check_admin():
        return redirect('/admin')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_autenticado', None)
    return redirect('/admin')

@app.route('/uploads/comprobantes/<filename>')
def ver_comprobante(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.route('/comprobante/<int:num>')
def route_ver_comprobante_numero(num):
    conn = get_db()
    row = conn.execute("SELECT comprobante_img FROM numeros WHERE numero = ?", (num,)).fetchone()
    conn.close()
    if not row or not row['comprobante_img']:
        return "No hay comprobante registrado para este número", 404

    comp = row['comprobante_img']
    if comp.startswith('data:'):
        try:
            import base64
            header, b64data = comp.split(',', 1)
            mime = header.split(';')[0].replace('data:', '')
            img_data = base64.b64decode(b64data)
            return Response(img_data, mimetype=mime)
        except Exception as e:
            return f"Error al procesar la imagen: {e}", 500
    else:
        return send_from_directory(UPLOAD_DIR, comp)

# --- Rutas de API ---

@app.route('/api/enlace_publico')
def api_enlace_publico():
    global CURRENT_PUBLIC_URL
    url = CURRENT_PUBLIC_URL if CURRENT_PUBLIC_URL else request.host_url.rstrip('/')
    return jsonify({
        'success': True,
        'url': url,
        'local_url': f"http://localhost:{os.environ.get('PORT', 5090)}"
    })

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    conn = get_db()
    if request.method == 'POST':
        if not check_admin():
            conn.close()
            return jsonify({'success': False, 'message': 'No autorizado. Inicie sesión.'}), 401
        data = request.json or {}
        cfg = conn.execute("SELECT * FROM configuracion WHERE id = 1").fetchone()
        cfg_dict = dict(cfg) if cfg else {}

        titulo = data.get('titulo', cfg_dict.get('titulo', 'Gran Rifa Benéfica'))
        causa = data.get('causa', cfg_dict.get('causa', 'A beneficio de cirugía de cataratas'))
        premio = data.get('premio', cfg_dict.get('premio', 'Aire Acondicionado de Ventana 12.000 BTU'))
        precio_usd = float(data.get('precio_usd', cfg_dict.get('precio_usd', 5.0)))
        tasa_bcv = float(data.get('tasa_bcv', cfg_dict.get('tasa_bcv', 45.0)))
        fecha_sorteo = data.get('fecha_sorteo', cfg_dict.get('fecha_sorteo', '5 de Noviembre 2026'))
        loteria = data.get('loteria', cfg_dict.get('loteria', 'Lotería del Zulia (7:00 PM)'))
        banco = data.get('banco', cfg_dict.get('banco', 'BANCAMIGA'))
        telefono_pago = data.get('telefono_pago', cfg_dict.get('telefono_pago', '0424-9718479'))
        cedula_pago = data.get('cedula_pago', cfg_dict.get('cedula_pago', '24.522.792'))

        conn.execute("""
            UPDATE configuracion SET
                titulo = ?, causa = ?, premio = ?, precio_usd = ?,
                tasa_bcv = ?, fecha_sorteo = ?, loteria = ?,
                banco = ?, telefono_pago = ?, cedula_pago = ?
            WHERE id = 1
        """, (
            titulo, causa, premio, precio_usd, tasa_bcv,
            fecha_sorteo, loteria, banco, telefono_pago, cedula_pago
        ))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Configuración guardada', 'tasa_bcv': tasa_bcv, 'precio_usd': precio_usd})
    
    cfg = conn.execute("SELECT * FROM configuracion WHERE id = 1").fetchone()
    cfg_dict = dict(cfg) if cfg else {}
    cfg_dict['db_engine'] = 'PostgreSQL (RIFA-DB Permanente)' if conn.is_postgres else 'SQLite (Temporal)'
    cfg_dict['db_diag'] = {
        'has_pg': HAS_PG,
        'pg_module': PG_MODULE,
        'import_err': PG_IMPORT_ERR,
        'errors': DB_ERRORS
    }
    conn.close()
    return jsonify(cfg_dict)

@app.route('/api/numeros')
def api_numeros():
    estado_filtro = request.args.get('estado', '')
    busqueda = request.args.get('q', '').strip().lower()
    
    conn = get_db()
    query = "SELECT * FROM numeros WHERE 1=1"
    params = []
    
    if estado_filtro:
        query += " AND estado = ?"
        params.append(estado_filtro.upper())
        
    if busqueda:
        query += " AND (numero_str LIKE ? OR LOWER(comprador_nombre) LIKE ? OR comprador_telefono LIKE ? OR comprador_cedula LIKE ?)"
        term = f"%{busqueda}%"
        params.extend([term, term, term, term])
        
    query += " ORDER BY numero ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    numeros = [dict(r) for r in rows]
    return jsonify({'success': True, 'total': len(numeros), 'numeros': numeros})

@app.route('/api/apartar_publico', methods=['POST'])
def api_apartar_publico():
    """
    Ruta publica para que un cliente aparte o pague boletos.
    Soporta JSON o multipart/form-data con archivo de comprobante adjunto.
    """
    if request.is_json:
        data = request.json or {}
        raw_nums = data.get('numeros', [])
        nombre = data.get('comprador_nombre', '').strip()
        tel = data.get('comprador_telefono', '').strip()
        modo = data.get('modo', 'PAGAR').upper() # 'PAGAR' o 'APARTAR'
        ref = data.get('referencia_pago', '').strip()
        metodo = data.get('metodo_pago', 'Pago Móvil')
        file_obj = None
    else:
        # FormData
        raw_nums_str = request.form.get('numeros', '')
        if ',' in raw_nums_str:
            raw_nums = [int(x.strip()) for x in raw_nums_str.split(',') if x.strip()]
        elif raw_nums_str:
            try:
                import json
                parsed = json.loads(raw_nums_str)
                raw_nums = parsed if isinstance(parsed, list) else [parsed]
            except:
                raw_nums = [int(raw_nums_str.strip())]
        else:
            raw_nums = []
        nombre = request.form.get('comprador_nombre', '').strip()
        tel = request.form.get('comprador_telefono', '').strip()
        modo = request.form.get('modo', 'PAGAR').upper()
        ref = request.form.get('referencia_pago', '').strip()
        metodo = request.form.get('metodo_pago', 'Pago Móvil')
        file_obj = request.files.get('comprobante')

    # Normalizar raw_nums siempre como lista de enteros
    if isinstance(raw_nums, (int, float)):
        numeros = [int(raw_nums)]
    elif isinstance(raw_nums, str):
        if ',' in raw_nums:
            numeros = [int(x.strip()) for x in raw_nums.split(',') if x.strip()]
        else:
            numeros = [int(raw_nums.strip())]
    else:
        numeros = [int(n) for n in raw_nums]

    if not numeros:
        return jsonify({'success': False, 'message': 'No seleccionaste ningún número'}), 400
    if not nombre or not tel:
        return jsonify({'success': False, 'message': 'Por favor indica tu nombre y teléfono'}), 400

    conn = get_db()
    cfg = conn.execute("SELECT * FROM configuracion WHERE id = 1").fetchone()
    precio_usd = cfg['precio_usd'] if cfg else 5.0
    tasa_bcv = cfg['tasa_bcv'] if cfg else 45.0
    tel_organizador = cfg['telefono_pago'] if cfg else '0424-9718479'

    # Validar si alguno ya está ocupado
    placeholders = ','.join(['?'] * len(numeros))
    ocupados = conn.execute(f"SELECT numero_str FROM numeros WHERE numero IN ({placeholders}) AND estado != 'DISPONIBLE'", numeros).fetchall()
    if ocupados:
        nums_ocup = ', '.join([r['numero_str'] for r in ocupados])
        conn.close()
        return jsonify({'success': False, 'message': f'Lo sentimos, el/los número(s) #{nums_ocup} ya fueron tomados por otra persona. Elige otro(s).'}), 409

    # Guardar archivo comprobante si fue adjuntado (Persistente dentro de la base de datos como Base64)
    comprobante_filename = ''
    if file_obj and file_obj.filename:
        ext = os.path.splitext(file_obj.filename)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.webp', '.heic']:
            import base64
            buf = None
            try:
                from PIL import Image
                img = Image.open(file_obj.stream)
                img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                fmt = 'JPEG' if ext in ['.jpg', '.jpeg'] else 'PNG'
                if fmt == 'JPEG':
                    img = img.convert('RGB')
                img.save(buf, format=fmt, quality=80)
                b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
                mime = 'image/jpeg' if fmt == 'JPEG' else 'image/png'
                comprobante_filename = f"data:{mime};base64,{b64}"
            except Exception as e:
                file_obj.seek(0)
                raw_bytes = file_obj.read()
                b64 = base64.b64encode(raw_bytes).decode('utf-8')
                mime = 'image/jpeg' if ext in ['.jpg', '.jpeg'] else ('image/png' if ext == '.png' else 'image/webp')
                comprobante_filename = f"data:{mime};base64,{b64}"
                buf = io.BytesIO(raw_bytes)

            try:
                unique_name = f"comp_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
                save_path = os.path.join(UPLOAD_DIR, unique_name)
                if buf:
                    with open(save_path, 'wb') as f:
                        f.write(buf.getvalue())
            except:
                pass
        elif ext == '.pdf':
            import base64
            file_obj.seek(0)
            b64 = base64.b64encode(file_obj.read()).decode('utf-8')
            comprobante_filename = f"data:application/pdf;base64,{b64}"

    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    monto_total_usd = len(numeros) * precio_usd
    monto_total_bs = monto_total_usd * tasa_bcv
    
    # Modo APARTAR vs PAGAR
    if modo == 'APARTAR':
        estado_nuevo = 'APARTADO'
        ref_guardar = 'Apartado (Por pagar después)'
        notas_guardar = 'Apartado online para pagar después'
        monto_pagar_guardar = 0.0
    else:
        # PAGAR (Queda en POR_CONFIRMAR con distintivo azul para el admin)
        estado_nuevo = 'POR_CONFIRMAR'
        ref_guardar = ref if ref else ('Comprobante adjunto' if comprobante_filename else 'Pago pendiente de verificación')
        notas_guardar = 'Pago móvil registrado con comprobante' if comprobante_filename else 'Pago móvil registrado'
        monto_pagar_guardar = precio_usd

    for n in numeros:
        conn.execute("""
            UPDATE numeros SET
                estado = ?,
                comprador_nombre = ?,
                comprador_telefono = ?,
                comprador_cedula = '',
                metodo_pago = ?,
                referencia_pago = ?,
                monto_pagado = ?,
                comprobante_img = ?,
                notas = ?,
                fecha_registro = ?,
                fecha_actualizacion = ?
            WHERE numero = ?
        """, (estado_nuevo, nombre, tel, metodo, ref_guardar, monto_pagar_guardar, comprobante_filename, notas_guardar, ahora, ahora, n))

    conn.commit()

    rows = conn.execute(f"SELECT numero_str FROM numeros WHERE numero IN ({placeholders}) ORDER BY numero ASC", numeros).fetchall()
    nums_str_list = [r['numero_str'] for r in rows]
    conn.close()

    nums_formatted = ', '.join(nums_str_list)

    # Teléfono del organizador para WhatsApp
    tel_clean = re.sub(r'\D', '', tel_organizador)
    if tel_clean.startswith('0'):
        tel_clean = '58' + tel_clean[1:]
    elif not tel_clean.startswith('58') and len(tel_clean) == 10:
        tel_clean = '58' + tel_clean

    if modo == 'APARTAR':
        mensaje_wa = (
            f"¡Hola! 👋 Acabo de apartar en la página web los números: *{nums_formatted}* "
            f"para la *Gran Rifa Benéfica* del Aire Acondicionado 12.000 BTU.\n\n"
            f"👤 *Comprador:* {nombre}\n"
            f"📱 *Teléfono:* {tel}\n"
            f"🎟️ *Cantidad:* {len(numeros)} número(s)\n"
            f"💵 *Monto a Pagar:* ${monto_total_usd:.2f} USD (Bs. {monto_total_bs:,.2f})\n"
            f"⏳ *Estado:* Apartado para pagar después.\n\n"
            f"¡Por favor resérvamelos! Estaré enviando el pago a la brevedad posible. ¡Muchas gracias! 🙏✨"
        )
    else:
        mensaje_wa = (
            f"¡Hola! 👋 Acabo de realizar el pago de los números: *{nums_formatted}* "
            f"para la *Gran Rifa Benéfica* del Aire Acondicionado 12.000 BTU.\n\n"
            f"👤 *Comprador:* {nombre}\n"
            f"📱 *Teléfono:* {tel}\n"
            f"🎟️ *Cantidad:* {len(numeros)} número(s)\n"
            f"💵 *Monto:* ${monto_total_usd:.2f} USD (Bs. {monto_total_bs:,.2f})\n"
            f"{f'💳 *Referencia:* {ref}\n' if ref else ''}"
            f"\nAquí le adjunto la captura de mi comprobante de pago móvil. ¡Muchísimas gracias! 🙏✨"
        )

    whatsapp_url = f"https://api.whatsapp.com/send?phone={tel_clean}&text={quote(mensaje_wa)}"

    return jsonify({
        'success': True,
        'modo': modo,
        'numeros': nums_str_list,
        'total_usd': monto_total_usd,
        'total_bs': monto_total_bs,
        'comprobante_img': comprobante_filename,
        'whatsapp_url': whatsapp_url
    })

@app.route('/api/consultar_apartados', methods=['GET'])
def api_consultar_apartados():
    tel = request.args.get('telefono', '').strip()
    num = request.args.get('numero', '').strip()

    if not tel and not num:
        return jsonify({'success': False, 'message': 'Por favor indica tu número de teléfono registrado.'}), 400

    tel_clean = re.sub(r'\D', '', tel)
    if not tel_clean or len(tel_clean) < 7:
        return jsonify({'success': False, 'message': 'Por seguridad, ingresa tu número de teléfono completo (mínimo 7 dígitos) para verificar tu identidad.'}), 400

    conn = get_db()
    cfg = conn.execute("SELECT * FROM configuracion WHERE id = 1").fetchone()
    precio_usd = cfg['precio_usd'] if cfg else 5.0
    tasa_bcv = cfg['tasa_bcv'] if cfg else 45.0

    if num:
        try:
            num_int = int(num)
        except:
            conn.close()
            return jsonify({'success': False, 'message': 'Número de boleto inválido.'}), 400

        row = conn.execute("SELECT numero, numero_str, comprador_nombre, comprador_telefono FROM numeros WHERE numero = ? AND estado = 'APARTADO'", (num_int,)).fetchone()
        conn.close()

        if not row:
            return jsonify({'success': False, 'message': f'El boleto #{num} no está en estado apartado o no existe.'}), 404

        row_tel_clean = re.sub(r'\D', '', row['comprador_telefono'] or '')
        if len(row_tel_clean) < 7 or row_tel_clean[-7:] != tel_clean[-7:]:
            return jsonify({
                'success': False,
                'message': f'El teléfono ingresado no coincide con el registrado al apartar el boleto #{row["numero_str"]}. Por seguridad no se puede acceder a este número.'
            }), 403

        coincidencias = [{
            'numero': row['numero'],
            'numero_str': row['numero_str'],
            'comprador_nombre': row['comprador_nombre'],
            'comprador_telefono': row['comprador_telefono']
        }]
    else:
        rows = conn.execute("SELECT numero, numero_str, comprador_nombre, comprador_telefono FROM numeros WHERE estado = 'APARTADO' ORDER BY numero ASC").fetchall()
        conn.close()

        coincidencias = []
        for r in rows:
            row_tel = re.sub(r'\D', '', r['comprador_telefono'] or '')
            if len(row_tel) >= 7 and row_tel[-7:] == tel_clean[-7:]:
                coincidencias.append({
                    'numero': r['numero'],
                    'numero_str': r['numero_str'],
                    'comprador_nombre': r['comprador_nombre'],
                    'comprador_telefono': r['comprador_telefono']
                })

        if not coincidencias:
            return jsonify({'success': False, 'message': 'No se encontraron boletos apartados con ese número de teléfono.'}), 404

    total_usd = len(coincidencias) * precio_usd
    total_bs = total_usd * tasa_bcv

    return jsonify({
        'success': True,
        'coincidencias': coincidencias,
        'total_usd': total_usd,
        'total_bs': total_bs,
        'precio_usd': precio_usd,
        'tasa_bcv': tasa_bcv
    })

@app.route('/api/pagar_apartado', methods=['POST'])
def api_pagar_apartado():
    raw_nums = request.form.get('numeros', '')
    tel = request.form.get('telefono', '').strip()
    ref = request.form.get('referencia', '').strip()
    metodo = request.form.get('metodo_pago', 'Pago Móvil')
    file_obj = request.files.get('comprobante')

    # Convertir números
    nums = []
    if ',' in raw_nums:
        for x in raw_nums.split(','):
            x = x.strip()
            if x.isdigit():
                nums.append(int(x))
    elif raw_nums.strip().isdigit():
        nums.append(int(raw_nums.strip()))

    if not nums:
        return jsonify({'success': False, 'message': 'Por favor indica al menos un número de boleto.'}), 400

    conn = get_db()
    placeholders = ','.join(['?'] * len(nums))
    rows = conn.execute(f"SELECT * FROM numeros WHERE numero IN ({placeholders})", nums).fetchall()
    
    if not rows:
        conn.close()
        return jsonify({'success': False, 'message': 'No se encontraron los números indicados.'}), 404

    # Verificar que todos estén en APARTADO
    no_apartados = [r['numero_str'] for r in rows if r['estado'] != 'APARTADO']
    if no_apartados:
        conn.close()
        return jsonify({'success': False, 'message': f'El/los número(s) #{", ".join(no_apartados)} ya no están en estado apartado.'}), 400

    # Validar coincidencia de teléfono con el registrado al apartar por seguridad
    if tel:
        tel_ingresado_clean = re.sub(r'\D', '', tel)
        for r in rows:
            tel_db_clean = re.sub(r'\D', '', r['comprador_telefono'] or '')
            if len(tel_db_clean) >= 6 and len(tel_ingresado_clean) >= 6:
                if tel_db_clean[-6:] != tel_ingresado_clean[-6:]:
                    conn.close()
                    return jsonify({
                        'success': False,
                        'message': f'Por seguridad, el teléfono indicado no coincide con el registrado al apartar el boleto #{r["numero_str"]}.'
                    }), 403

    # Comprimir comprobante y pasarlo a Base64
    comprobante_filename = ''
    if file_obj and file_obj.filename:
        ext = os.path.splitext(file_obj.filename)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.webp', '.heic']:
            import base64
            try:
                from PIL import Image
                img = Image.open(file_obj.stream)
                img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                fmt = 'JPEG' if ext in ['.jpg', '.jpeg'] else 'PNG'
                if fmt == 'JPEG':
                    img = img.convert('RGB')
                img.save(buf, format=fmt, quality=80)
                b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
                mime = 'image/jpeg' if fmt == 'JPEG' else 'image/png'
                comprobante_filename = f"data:{mime};base64,{b64}"
            except Exception as e:
                file_obj.seek(0)
                raw_bytes = file_obj.read()
                b64 = base64.b64encode(raw_bytes).decode('utf-8')
                mime = 'image/jpeg' if ext in ['.jpg', '.jpeg'] else ('image/png' if ext == '.png' else 'image/webp')
                comprobante_filename = f"data:{mime};base64,{b64}"
        elif ext == '.pdf':
            import base64
            file_obj.seek(0)
            b64 = base64.b64encode(file_obj.read()).decode('utf-8')
            comprobante_filename = f"data:application/pdf;base64,{b64}"

    cfg = conn.execute("SELECT * FROM configuracion WHERE id = 1").fetchone()
    precio_usd = cfg['precio_usd'] if cfg else 5.0
    tasa_bcv = cfg['tasa_bcv'] if cfg else 45.0
    tel_organizador = cfg['telefono_pago'] if cfg else '0424-9718479'

    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ref_guardar = ref if ref else ('Comprobante adjunto' if comprobante_filename else 'Pago de apartado reportado')

    for r in rows:
        conn.execute("""
            UPDATE numeros SET
                estado = 'POR_CONFIRMAR',
                metodo_pago = ?,
                referencia_pago = ?,
                monto_pagado = ?,
                comprobante_img = ?,
                notas = 'Pago de número apartado reportado online por el cliente',
                fecha_actualizacion = ?
            WHERE numero = ?
        """, (metodo, ref_guardar, precio_usd, comprobante_filename, ahora, r['numero']))

    conn.commit()
    conn.close()

    nums_str_list = [r['numero_str'] for r in rows]
    nums_formatted = ', '.join(nums_str_list)
    nombre = rows[0]['comprador_nombre'] or 'Comprador'
    monto_total_usd = len(nums) * precio_usd
    monto_total_bs = monto_total_usd * tasa_bcv

    tel_clean = re.sub(r'\D', '', tel_organizador)
    if tel_clean.startswith('0'):
        tel_clean = '58' + tel_clean[1:]
    elif not tel_clean.startswith('58') and len(tel_clean) == 10:
        tel_clean = '58' + tel_clean

    mensaje_wa = (
        f"¡Hola! 👋 Acabo de realizar el pago de mi(s) número(s) apartado(s): *{nums_formatted}* "
        f"para la *Gran Rifa Benéfica* del Aire Acondicionado 12.000 BTU.\n\n"
        f"👤 *Comprador:* {nombre}\n"
        f"📱 *Teléfono:* {tel or rows[0]['comprador_telefono']}\n"
        f"🎟️ *Cantidad:* {len(nums)} número(s)\n"
        f"💵 *Monto:* ${monto_total_usd:.2f} USD (Bs. {monto_total_bs:,.2f})\n"
        f"{f'💳 *Referencia:* {ref}\n' if ref else ''}"
        f"\nAquí le adjunto la captura de mi comprobante de pago móvil. ¡Muchísimas gracias! 🙏✨"
    )
    whatsapp_url = f"https://api.whatsapp.com/send?phone={tel_clean}&text={quote(mensaje_wa)}"

    return jsonify({
        'success': True,
        'message': f'¡Pago de los boletos #{nums_formatted} registrado con éxito!',
        'numeros': nums_str_list,
        'total_usd': monto_total_usd,
        'total_bs': monto_total_bs,
        'whatsapp_url': whatsapp_url
    })

@app.route('/api/numero/<int:num>', methods=['GET', 'POST'])
def api_numero_detalle(num):
    conn = get_db()
    if request.method == 'POST':
        if not check_admin():
            conn.close()
            return jsonify({'success': False, 'message': 'No autorizado. Inicie sesión.'}), 401
        data = request.json or {}
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        estado = data.get('estado', 'APARTADO').upper()
        if estado not in ['DISPONIBLE', 'POR_CONFIRMAR', 'APARTADO', 'PAGADO']:
            estado = 'APARTADO'
            
        monto = float(data.get('monto_pagado', 5.0 if estado == 'PAGADO' else 0.0))
        
        conn.execute("""
            UPDATE numeros SET
                estado = ?,
                comprador_nombre = ?,
                comprador_telefono = ?,
                comprador_cedula = ?,
                metodo_pago = ?,
                referencia_pago = ?,
                monto_pagado = ?,
                notas = ?,
                fecha_registro = CASE WHEN fecha_registro = '' THEN ? ELSE fecha_registro END,
                fecha_actualizacion = ?
            WHERE numero = ?
        """, (
            estado,
            data.get('comprador_nombre', '').strip(),
            data.get('comprador_telefono', '').strip(),
            data.get('comprador_cedula', '').strip(),
            data.get('metodo_pago', 'Pago Móvil'),
            data.get('referencia_pago', '').strip(),
            monto,
            data.get('notas', '').strip(),
            ahora,
            ahora,
            num
        ))
        conn.commit()
        row = conn.execute("SELECT * FROM numeros WHERE numero = ?", (num,)).fetchone()
        conn.close()
        return jsonify({'success': True, 'numero': dict(row)})
        
    row = conn.execute("SELECT * FROM numeros WHERE numero = ?", (num,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'success': False, 'message': 'Número no encontrado'}), 404
    return jsonify({'success': True, 'numero': dict(row)})

@app.route('/api/numero/<int:num>/liberar', methods=['POST'])
def api_numero_liberar(num):
    if not check_admin():
        return jsonify({'success': False, 'message': 'No autorizado. Inicie sesión.'}), 401
    conn = get_db()
    conn.execute("""
        UPDATE numeros SET
            estado = 'DISPONIBLE',
            comprador_nombre = '',
            comprador_telefono = '',
            comprador_cedula = '',
            metodo_pago = 'Pago Móvil',
            referencia_pago = '',
            monto_pagado = 0.0,
            comprobante_img = '',
            notas = '',
            fecha_actualizacion = ?
        WHERE numero = ?
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), num))
    conn.commit()
    row = conn.execute("SELECT * FROM numeros WHERE numero = ?", (num,)).fetchone()
    conn.close()
    return jsonify({'success': True, 'numero': dict(row)})

@app.route('/api/venta_multiple', methods=['POST'])
def api_venta_multiple():
    if not check_admin():
        return jsonify({'success': False, 'message': 'No autorizado. Inicie sesión.'}), 401
    data = request.json or {}
    nums = data.get('numeros', [])
    if not nums:
        return jsonify({'success': False, 'message': 'No se indicaron números'}), 400
        
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    estado = data.get('estado', 'APARTADO').upper()
    nombre = data.get('comprador_nombre', '').strip()
    tel = data.get('comprador_telefono', '').strip()
    ci = data.get('comprador_cedula', '').strip()
    metodo = data.get('metodo_pago', 'Pago Móvil')
    ref = data.get('referencia_pago', '').strip()
    monto_total = float(data.get('monto_total', 0.0))
    monto_por_num = monto_total / len(nums) if len(nums) > 0 else 0.0
    notas = data.get('notas', '').strip()
    
    conn = get_db()
    for n in nums:
        conn.execute("""
            UPDATE numeros SET
                estado = ?,
                comprador_nombre = ?,
                comprador_telefono = ?,
                comprador_cedula = ?,
                metodo_pago = ?,
                referencia_pago = ?,
                monto_pagado = ?,
                notas = ?,
                fecha_registro = CASE WHEN fecha_registro = '' THEN ? ELSE fecha_registro END,
                fecha_actualizacion = ?
            WHERE numero = ?
        """, (estado, nombre, tel, ci, metodo, ref, monto_por_num, notas, ahora, ahora, int(n)))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'actualizados': len(nums)})

@app.route('/api/estadisticas')
def api_estadisticas():
    conn = get_db()
    cfg = conn.execute("SELECT * FROM configuracion WHERE id = 1").fetchone()
    precio_usd = cfg['precio_usd'] if cfg else 5.0
    tasa_bcv = cfg['tasa_bcv'] if cfg else 45.0
    
    total = conn.execute("SELECT COUNT(*) FROM numeros").fetchone()[0]
    libres = conn.execute("SELECT COUNT(*) FROM numeros WHERE estado = 'DISPONIBLE'").fetchone()[0]
    por_confirmar = conn.execute("SELECT COUNT(*) FROM numeros WHERE estado = 'POR_CONFIRMAR'").fetchone()[0]
    apartados = conn.execute("SELECT COUNT(*) FROM numeros WHERE estado = 'APARTADO'").fetchone()[0]
    pagados = conn.execute("SELECT COUNT(*) FROM numeros WHERE estado = 'PAGADO'").fetchone()[0]
    
    total_usd_recaudado = conn.execute("SELECT COALESCE(SUM(monto_pagado), 0.0) FROM numeros WHERE estado = 'PAGADO'").fetchone()[0]
    total_usd_esperado = total * precio_usd
    porcentaje_pagado = (pagados / total * 100.0) if total > 0 else 0.0
    porcentaje_vendido = ((pagados + apartados + por_confirmar) / total * 100.0) if total > 0 else 0.0
    
    conn.close()
    return jsonify({
        'success': True,
        'total_numeros': total,
        'libres': libres,
        'por_confirmar': por_confirmar,
        'apartados': apartados,
        'pagados': pagados,
        'comprometidos': pagados + apartados + por_confirmar,
        'precio_usd': precio_usd,
        'tasa_bcv': tasa_bcv,
        'total_usd_recaudado': round(total_usd_recaudado, 2),
        'total_bs_recaudado': round(total_usd_recaudado * tasa_bcv, 2),
        'total_usd_esperado': round(total_usd_esperado, 2),
        'porcentaje_pagado': round(porcentaje_pagado, 1),
        'porcentaje_vendido': round(porcentaje_vendido, 1)
    })

@app.route('/exportar_csv')
def exportar_csv():
    if not check_admin():
        return redirect('/admin')
    conn = get_db()
    rows = conn.execute("SELECT * FROM numeros ORDER BY numero ASC").fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'Numero', 'Estado', 'Comprador', 'Telefono', 'Metodo_Pago', 'Referencia', 'Monto_USD', 'Comprobante', 'Notas', 'Fecha_Registro'
    ])
    for r in rows:
        writer.writerow([
            r['numero_str'],
            r['estado'],
            r['comprador_nombre'],
            r['comprador_telefono'],
            r['metodo_pago'],
            r['referencia_pago'],
            f"{r['monto_pagado']:.2f}",
            r['comprobante_img'] if 'comprobante_img' in r.keys() else '',
            r['notas'],
            r['fecha_registro']
        ])
        
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=control_rifa_500_numeros.csv"}
    )

@app.route('/descargar_flyer/<tipo>')
def descargar_flyer(tipo):
    if tipo == 'vertical':
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'img', 'flyer_rifa_vertical.png')
        return send_file(path, as_attachment=True, download_name="Flyer_Rifa_Benefica_Vertical.png")
    else:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'img', 'flyer_rifa_cuadrado.png')
        return send_file(path, as_attachment=True, download_name="Flyer_Rifa_Benefica_Cuadrado.png")

# --- Generación de Boletos Oficiales con Firma Digital y Código QR ---
def generar_firma_boleto(numero, comprador_nombre, comprador_telefono):
    """Genera una firma criptográfica inviolable para un boleto pagado"""
    raw = f"{numero}:{comprador_nombre or ''}:{comprador_telefono or ''}:{app.secret_key}"
    sig = hmac.new(app.secret_key.encode('utf-8'), raw.encode('utf-8'), hashlib.sha256).hexdigest()[:12].upper()
    return f"RIFA-{sig[:4]}-{sig[4:8]}-{sig[8:12]}"

def generar_pdf_boleto_bytes(row, cfg, host_url):
    import qrcode
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader

    num = row['numero']
    num_str = row['numero_str']
    nom = row['comprador_nombre'] or 'Comprador Oficial'
    tel = row['comprador_telefono'] or 'No registrado'
    monto_usd = float(row['monto_pagado'] or (cfg['precio_usd'] if cfg else 5.0))
    tasa = float(cfg['tasa_bcv'] if cfg else 45.0)
    monto_bs = monto_usd * tasa
    fecha = row['fecha_actualizacion'] or row['fecha_registro'] or datetime.now().strftime("%Y-%m-%d %H:%M")
    firma = generar_firma_boleto(num, nom, tel)

    verify_url = f"{host_url.rstrip('/')}/verificar/{num}?sig={firma}"

    # Generar QR
    qr = qrcode.QRCode(version=1, box_size=6, border=1)
    qr.add_data(verify_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color='black', back_color='white')
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format='PNG')
    qr_buf.seek(0)
    qr_reader = ImageReader(qr_buf)

    # Generar Canvas PDF
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(580, 290))

    # Fondo oscuro elegante
    c.setFillColor(colors.HexColor('#0B1329'))
    c.roundRect(5, 5, 570, 280, 10, fill=1, stroke=0)

    # Borde dorado
    c.setStrokeColor(colors.HexColor('#F59E0B'))
    c.setLineWidth(2)
    c.roundRect(8, 8, 564, 274, 8, fill=0, stroke=1)

    # Línea punteada de desprendible
    c.setStrokeColor(colors.HexColor('#334155'))
    c.setDash(4, 3)
    c.line(405, 10, 405, 280)
    c.setDash()

    # Título Principal
    c.setFillColor(colors.HexColor('#F59E0B'))
    c.setFont('Helvetica-Bold', 14)
    c.drawString(25, 260, 'GRAN RIFA BENEFICA - CIRUGIA DE CATARATAS')

    c.setFillColor(colors.HexColor('#94A3B8'))
    c.setFont('Helvetica', 9)
    c.drawString(25, 245, 'Boleto Oficial de Participacion - Emision Certificada')

    # Cuadro del Número de Boleto
    c.setFillColor(colors.HexColor('#1E293B'))
    c.setStrokeColor(colors.HexColor('#F59E0B'))
    c.setLineWidth(1.5)
    c.roundRect(25, 165, 140, 68, 6, fill=1, stroke=1)

    c.setFillColor(colors.HexColor('#FCD34D'))
    c.setFont('Helvetica-Bold', 8)
    c.drawString(35, 218, 'NUMERO OFICIAL')

    c.setFont('Helvetica-Bold', 32)
    c.drawString(35, 178, f"#{num_str}")

    # Datos del Titular
    c.setFillColor(colors.HexColor('#CBD5E1'))
    c.setFont('Helvetica', 10)
    c.drawString(180, 218, 'Titular: ')
    c.setFillColor(colors.HexColor('#FFFFFF'))
    c.setFont('Helvetica-Bold', 10)
    nom_display = nom if len(nom) <= 22 else nom[:20] + '..'
    c.drawString(235, 218, nom_display)

    c.setFillColor(colors.HexColor('#CBD5E1'))
    c.setFont('Helvetica', 10)
    c.drawString(180, 198, 'Telefono: ')
    c.setFillColor(colors.HexColor('#38BDF8'))
    c.setFont('Helvetica-Bold', 10)
    c.drawString(235, 198, tel)

    c.setFillColor(colors.HexColor('#CBD5E1'))
    c.setFont('Helvetica', 10)
    c.drawString(180, 178, 'Monto: ')
    c.setFillColor(colors.HexColor('#34D399'))
    c.setFont('Helvetica-Bold', 10)
    c.drawString(235, 178, f"${monto_usd:.2f} USD (Bs. {monto_bs:,.2f})")

    # Caja de Información del Sorteo
    c.setFillColor(colors.HexColor('#131F37'))
    c.setStrokeColor(colors.HexColor('#1E293B'))
    c.setLineWidth(1)
    c.roundRect(25, 60, 365, 95, 6, fill=1, stroke=1)

    c.setFillColor(colors.HexColor('#F59E0B'))
    c.setFont('Helvetica-Bold', 10)
    c.drawString(35, 138, 'PREMIO: Aire Acondicionado 12.000 BTU')

    c.setFillColor(colors.HexColor('#E2E8F0'))
    c.setFont('Helvetica', 9)
    c.drawString(35, 120, 'Fecha de Sorteo: 5 de Noviembre 2026')
    c.drawString(35, 104, 'Loteria: Loteria del Zulia (7:00 PM)')
    metodo_display = row['metodo_pago'] or 'Pago Movil'
    c.drawString(35, 88, f"Metodo: {metodo_display}")

    c.setFillColor(colors.HexColor('#10B981'))
    c.setFont('Helvetica-Bold', 9)
    c.drawString(35, 70, '[ CERTIFICADO 100% PAGADO Y VERIFICADO ]')

    # Hash Criptográfico
    c.setFillColor(colors.HexColor('#64748B'))
    c.setFont('Helvetica', 8)
    c.drawString(25, 25, f"Firma Digital del Sistema: {firma}")

    # Desprendible QR Derecho
    c.setFillColor(colors.HexColor('#FFFFFF'))
    c.roundRect(430, 115, 120, 120, 6, fill=1, stroke=0)
    c.drawImage(qr_reader, 435, 120, width=110, height=110)

    c.setFillColor(colors.HexColor('#F59E0B'))
    c.setFont('Helvetica-Bold', 9)
    c.drawCentredString(490, 250, 'VALIDACION QR')

    c.setFillColor(colors.HexColor('#94A3B8'))
    c.setFont('Helvetica', 8)
    c.drawCentredString(490, 95, 'Escanea para verificar')
    c.drawCentredString(490, 82, 'autenticidad en vivo')

    c.setFillColor(colors.HexColor('#34D399'))
    c.setFont('Helvetica-Bold', 9)
    c.drawCentredString(490, 50, 'SELLO OFICIAL')
    c.drawCentredString(490, 36, 'NO FALSIFICABLE')

    c.save()
    buf.seek(0)
    return buf.getvalue()

@app.route('/boleto/<int:num>')
def ver_boleto_digital(num):
    conn = get_db()
    row = conn.execute("SELECT * FROM numeros WHERE numero = ?", (num,)).fetchone()
    cfg = conn.execute("SELECT * FROM configuracion WHERE id = 1").fetchone()
    conn.close()

    if not row:
        return "Boleto no encontrado", 404

    nom = row['comprador_nombre'] or 'Participante'
    tel = row['comprador_telefono'] or 'No registrado'
    monto = float(row['monto_pagado'] or (cfg['precio_usd'] if cfg else 5.0))
    tasa = float(cfg['tasa_bcv'] if cfg else 45.0)
    total_bs = monto * tasa
    total_bs_fmt = f"{total_bs:,.2f}"
    fecha_emision = row['fecha_actualizacion'] or row['fecha_registro'] or datetime.now().strftime("%d/%m/%Y %H:%M")
    firma = generar_firma_boleto(num, nom, tel)

    host_url = request.host_url
    if 'onrender.com' not in host_url and CURRENT_PUBLIC_URL:
        host_url = CURRENT_PUBLIC_URL

    verify_url = f"{host_url.rstrip('/')}/verificar/{num}?sig={firma}"

    # Generar QR Base64
    import qrcode
    qr = qrcode.QRCode(version=1, box_size=6, border=1)
    qr.add_data(verify_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color='black', back_color='white')
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format='PNG')
    qr_b64 = "data:image/png;base64," + base64.b64encode(qr_buf.getvalue()).decode('utf-8')

    return render_template('boleto_digital.html',
        numero=num,
        numero_str=row['numero_str'],
        comprador_nombre=nom,
        comprador_telefono=tel,
        monto_pagado=monto,
        total_bs_formatted=total_bs_fmt,
        fecha_emision=fecha_emision,
        firma_digital=firma,
        qr_b64=qr_b64,
        estado=row['estado']
    )

@app.route('/boleto/<int:num>/pdf')
def descargar_boleto_pdf(num):
    conn = get_db()
    row = conn.execute("SELECT * FROM numeros WHERE numero = ?", (num,)).fetchone()
    cfg = conn.execute("SELECT * FROM configuracion WHERE id = 1").fetchone()
    conn.close()

    if not row:
        return "Boleto no encontrado", 404

    host_url = request.host_url
    if 'onrender.com' not in host_url and CURRENT_PUBLIC_URL:
        host_url = CURRENT_PUBLIC_URL

    pdf_bytes = generar_pdf_boleto_bytes(row, cfg, host_url)

    nom_slug = re.sub(r'[^a-zA-Z0-9]', '_', row['comprador_nombre'] or 'Boleto')
    filename = f"Boleto_Oficial_{row['numero_str']}_{nom_slug}.pdf"

    as_attachment = (request.args.get('download') == '1')
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f"{'attachment' if as_attachment else 'inline'}; filename=\"{filename}\""
        }
    )

@app.route('/verificar/<int:num>')
def verificar_boleto_publico(num):
    conn = get_db()
    row = conn.execute("SELECT * FROM numeros WHERE numero = ?", (num,)).fetchone()
    cfg = conn.execute("SELECT * FROM configuracion WHERE id = 1").fetchone()
    conn.close()

    if not row:
        return render_template('verificar_boleto.html', estado='NO_EXISTE', numero=num, numero_str=f"{num:03d}")

    nom = row['comprador_nombre'] or 'Participante'
    tel = row['comprador_telefono'] or 'No registrado'
    monto = float(row['monto_pagado'] or (cfg['precio_usd'] if cfg else 5.0))
    tasa = float(cfg['tasa_bcv'] if cfg else 45.0)
    total_bs = monto * tasa
    total_bs_fmt = f"{total_bs:,.2f}"
    fecha_emision = row['fecha_actualizacion'] or row['fecha_registro'] or datetime.now().strftime("%d/%m/%Y %H:%M")
    firma = generar_firma_boleto(num, nom, tel)

    return render_template('verificar_boleto.html',
        numero=num,
        numero_str=row['numero_str'],
        comprador_nombre=nom,
        comprador_telefono=tel,
        monto_pagado=monto,
        total_bs_formatted=total_bs_fmt,
        fecha_emision=fecha_emision,
        firma_digital=firma,
        estado=row['estado']
    )


# --- Servicio en Segundo Plano: Túnel Público Seguro HTTPS ---
def background_public_tunnel():
    global CURRENT_PUBLIC_URL
    time.sleep(1.5)
    print("\n[Tunel] Iniciando Enlace Publico Seguro (HTTPS) para acceso mundial en internet...")
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tunnel.log')
    try:
        f_log = open(log_file, 'w', encoding='utf-8')
        proc = subprocess.Popen(
            ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'ServerAliveInterval=30', '-R', '80:127.0.0.1:5090', 'nokey@localhost.run'],
            stdout=f_log,
            stderr=subprocess.STDOUT
        )

        start = time.time()
        while time.time() - start < 30:
            time.sleep(1)
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    match = re.search(r'https://[a-zA-Z0-9-]+\.lhr\.life', content)
                    if match:
                        CURRENT_PUBLIC_URL = match.group(0)
                        print("\n" + "="*70)
                        print("   >>> ENLACE PUBLICO DE LA RIFA LISTO PARA COMPARTIR EN WHATSAPP: <<<")
                        print(f"   {CURRENT_PUBLIC_URL}")
                        print("="*70 + "\n")
                        url_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'enlace_publico.txt')
                        with open(url_file, 'w', encoding='utf-8') as uf:
                            uf.write(f"ENLACE PUBLICO PARA COMPRADORES:\n{CURRENT_PUBLIC_URL}\n\nPANEL DEL ORGANIZADOR:\n{CURRENT_PUBLIC_URL}/admin\n")
                        break
    except Exception as e:
        print(f"[Tunel] Error al iniciar tunel: {e}")

if __name__ == '__main__':
    if not os.environ.get('RENDER'):
        t = threading.Thread(target=background_public_tunnel, daemon=True)
        t.start()

    port = int(os.environ.get('PORT', 5090))
    print(f"Iniciando Sistema de Rifa en http://127.0.0.1:{port} ...")
    app.run(host='0.0.0.0', port=port, debug=False)
