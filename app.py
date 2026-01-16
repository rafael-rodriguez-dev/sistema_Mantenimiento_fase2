import os
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
import qrcode
import io

app = Flask(__name__)
app.secret_key = 'super_secreto_clave_segura' # Necesario para sesiones

# --- CONFIGURACIÓN DE BASE DE DATOS INTELIGENTE ---
database_url = os.environ.get('DATABASE_URL')

if database_url:
    # NUBE (Render) ☁️
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # LOCAL (PC) 💻
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mantenimiento_v2.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- CONFIGURACIÓN LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Si no estás logueado, te manda aquí

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- MODELOS (TABLAS) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    direccion = db.Column(db.String(200), nullable=True)
    equipos = db.relationship('Equipo', backref='cliente', lazy=True)

class Equipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
    serial = db.Column(db.String(50), unique=True, nullable=False)
    ubicacion = db.Column(db.String(100), nullable=False)
    estado = db.Column(db.String(20), default="Operativo")
    observaciones = db.Column(db.String(300), nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)

# --- RUTA DE INSTALACIÓN (SETUP MEJORADO) ---
@app.route('/setup-fase2')
def setup_db():
    try:
        with app.app_context():
            db.create_all() # Crea tablas (incluyendo User)
            
            # 1. Crear Usuario Admin si no existe
            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin')
                admin.set_password('admin123') # <--- CONTRASEÑA POR DEFECTO
                db.session.add(admin)
                mensaje_user = "👤 Usuario 'admin' creado (Clave: admin123)."
            else:
                mensaje_user = "👤 El usuario 'admin' ya existe."

            # 2. Crear Clientes Base
            if not Cliente.query.first():
                c1 = Cliente(nombre="GNB Sudameris - Torre A", direccion="Calle 72")
                c2 = Cliente(nombre="Edificio Avianca", direccion="Calle 26")
                db.session.add(c1)
                db.session.add(c2)
                mensaje_cli = "🏢 Clientes base creados."
            else:
                mensaje_cli = "🏢 Clientes ya existían."
            
            db.session.commit()
            return f"✅ SETUP COMPLETO:<br>{mensaje_user}<br>{mensaje_cli}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# --- RUTAS PRINCIPALES ---
@app.route('/')
# @login_required  <--- AÚN NO ACTIVAMOS ESTO PARA NO BLOQUEARTE
def dashboard():
    cliente_id_filtrado = request.args.get('cliente_id')
    todos_los_clientes = Cliente.query.all()
    cliente_actual = None
    if cliente_id_filtrado:
        equipos_mostrar = Equipo.query.filter_by(cliente_id=cliente_id_filtrado).all()
        cliente_actual = Cliente.query.get(cliente_id_filtrado)
    else:
        equipos_mostrar = Equipo.query.all()

    return render_template('index.html', 
                           equipos=equipos_mostrar, 
                           clientes=todos_los_clientes,
                           cliente_actual=cliente_actual)

# --- API (JSON) ---
@app.route('/api/clientes', methods=['GET'])
def obtener_clientes():
    clientes = Cliente.query.all()
    lista = [{"id": c.id, "nombre": c.nombre} for c in clientes]
    return jsonify(lista)

@app.route('/api/clientes', methods=['POST'])
def crear_cliente():
    datos = request.json
    try:
        nuevo_cliente = Cliente(
            nombre=datos['nombre'],
            direccion=datos.get('direccion', 'Sin dirección')
        )
        db.session.add(nuevo_cliente)
        db.session.commit()
        return jsonify({"mensaje": "Cliente creado exitosamente"})
    except Exception as e:
        return jsonify({"mensaje": f"Error: {str(e)}"}), 400

@app.route('/api/equipos', methods=['POST'])
def agregar_equipo():
    data = request.json
    try:
        nuevo = Equipo(
            cliente_id=data['cliente_id'],
            nombre=data['nombre'], 
            tipo=data['tipo'], 
            serial=data['serial'], 
            ubicacion=data['ubicacion'],
            observaciones=data.get('observaciones', '')
        )
        db.session.add(nuevo)
        db.session.commit()
        return jsonify({"mensaje": "Equipo registrado"})
    except Exception as e:
        return jsonify({"mensaje": "Error: Posible serial repetido"}), 400

@app.route('/api/equipos/<int:id>', methods=['PUT'])
def editar_equipo(id):
    data = request.json
    equipo = Equipo.query.get(id)
    if not equipo:
        return jsonify({"mensaje": "Equipo no encontrado"}), 404
    try:
        equipo.nombre = data['nombre']
        equipo.tipo = data['tipo']
        equipo.serial = data['serial']
        equipo.ubicacion = data['ubicacion']
        equipo.observaciones = data.get('observaciones', '')
        equipo.cliente_id = data['cliente_id']
        db.session.commit()
        return jsonify({"mensaje": "Equipo actualizado"})
    except Exception as e:
        return jsonify({"mensaje": "Error al actualizar"}), 400

@app.route('/api/equipos/<int:id>', methods=['DELETE'])
def eliminar_equipo(id):
    equipo = Equipo.query.get(id)
    if equipo:
        db.session.delete(equipo)
        db.session.commit()
        return jsonify({"mensaje": "Equipo eliminado"})
    return jsonify({"mensaje": "No encontrado"}), 404

# --- EXPORTAR PDF ---
@app.route('/exportar-pdf')
def exportar_pdf():
    cliente_id = request.args.get('cliente_id')
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setTitle("Reporte de Mantenimiento")

    titulo_reporte = "Reporte Global de Activos"
    subtitulo = "Listado General"
    equipos = []

    if cliente_id:
        cliente = Cliente.query.get(cliente_id)
        if cliente:
            titulo_reporte = f"Cliente: {cliente.nombre}"
            subtitulo = f"Sede: {cliente.direccion or 'Principal'}"
            equipos = cliente.equipos
    else:
        equipos = Equipo.query.all()

    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 750, titulo_reporte)
    c.setFont("Helvetica", 12)
    c.drawString(50, 735, subtitulo)
    c.line(50, 725, 550, 725)
    y = 660  
    
    for equipo in equipos:
        if y < 100:
            c.showPage()
            c.setFont("Helvetica-Bold", 10)
            c.drawString(50, 750, f"Continuación: {titulo_reporte}")
            c.line(50, 740, 550, 740)
            y = 700

        contenido_qr = f"ID:{equipo.id}\nSN:{equipo.serial}"
        qr = qrcode.QRCode(box_size=5, border=1)
        qr.add_data(contenido_qr)
        qr.make(fit=True)
        img_qr = qr.make_image(fill_color="black", back_color="white")
        qr_buffer = io.BytesIO()
        img_qr.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        c.drawImage(ImageReader(qr_buffer), 50, y, width=50, height=50)

        c.setFont("Helvetica-Bold", 12)
        c.drawString(120, y + 35, f"{equipo.nombre}")
        c.setFont("Helvetica", 10)
        c.drawString(120, y + 20, f"Tipo: {equipo.tipo} | Serial: {equipo.serial}")
        c.drawString(120, y + 5, f"Ubicación: {equipo.ubicacion}")
        c.setFont("Helvetica-Oblique", 9)
        c.setFillColor(colors.gray)
        obs = equipo.observaciones if equipo.observaciones else "Sin obs"
        c.drawString(120, y - 8, f"Obs: {obs}")
        c.setFillColor(colors.black)
        
        if equipo.estado == "Falla":
            c.setFillColor(colors.red)
        else:
            c.setFillColor(colors.green)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(450, y + 35, equipo.estado)
        c.setFillColor(colors.black)

        c.setStrokeColor(colors.lightgrey)
        c.line(50, y - 15, 550, y - 15)
        y -= 80

    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="reporte.pdf", mimetype='application/pdf')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)