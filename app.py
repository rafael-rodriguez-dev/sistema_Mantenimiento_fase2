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
# Clave secreta para sesiones
app.secret_key = 'super_secreto_clave_segura_gnb'

# --- CONFIGURACIÓN DE BASE DE DATOS ---
database_url = os.environ.get('DATABASE_URL')

if database_url:
    # NUBE (Render) - Corrección automática
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # LOCAL (PC)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mantenimiento_v2.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- MODELOS ---
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

    # ESTA ES LA FUNCIÓN NUEVA QUE ARREGLA EL ERROR
    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'tipo': self.tipo,
            'serial': self.serial,
            'ubicacion': self.ubicacion,
            'estado': self.estado,
            'observaciones': self.observaciones,
            'cliente_id': self.cliente_id
        }

# --- RUTAS ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Usuario o contraseña incorrectos')
            
    return render_template('login.html')

@app.route('/login-invitado')
def login_invitado():
    user = User.query.filter_by(username='invitado').first()
    if user:
        login_user(user)
        return redirect(url_for('dashboard'))
    else:
        flash("Error: Ejecuta /setup-fase2 primero")
        return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/setup-fase2')
def setup_db():
    try:
        with app.app_context():
            db.create_all()
            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin')
                admin.set_password('admin123')
                db.session.add(admin)
            
            if not User.query.filter_by(username='invitado').first():
                guest = User(username='invitado')
                guest.set_password('invitado')
                db.session.add(guest)

            if not Cliente.query.first():
                c1 = Cliente(nombre="GNB Sudameris - Torre A", direccion="Calle 72")
                c2 = Cliente(nombre="Edificio Avianca", direccion="Calle 26")
                db.session.add(c1)
                db.session.add(c2)
            
            db.session.commit()
            return "✅ SETUP COMPLETO. Usuarios 'admin' e 'invitado' creados."
    except Exception as e:
        return f"❌ Error: {str(e)}"

@app.route('/')
@login_required
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
                           cliente_actual=cliente_actual,
                           user=current_user)

# --- API ---
@app.route('/api/clientes', methods=['GET'])
@login_required
def obtener_clientes():
    clientes = Cliente.query.all()
    lista = [{"id": c.id, "nombre": c.nombre} for c in clientes]
    return jsonify(lista)

@app.route('/api/clientes', methods=['POST'])
@login_required
def crear_cliente():
    if current_user.username == 'invitado':
        return jsonify({"mensaje": "⚠️ Modo Invitado: Solo lectura"}), 403
    datos = request.json
    try:
        nuevo = Cliente(nombre=datos['nombre'], direccion=datos.get('direccion', ''))
        db.session.add(nuevo)
        db.session.commit()
        return jsonify({"mensaje": "Cliente creado"})
    except Exception as e:
        return jsonify({"mensaje": str(e)}), 400

@app.route('/api/equipos', methods=['POST'])
@login_required
def agregar_equipo():
    if current_user.username == 'invitado':
        return jsonify({"mensaje": "⚠️ Modo Invitado: Solo lectura"}), 403
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
        return jsonify({"mensaje": "Error: Serial repetido"}), 400

@app.route('/api/equipos/<int:id>', methods=['PUT'])
@login_required
def editar_equipo(id):
    if current_user.username == 'invitado':
        return jsonify({"mensaje": "⚠️ Modo Invitado: Solo lectura"}), 403
    data = request.json
    equipo = Equipo.query.get(id)
    if not equipo: return jsonify({"mensaje": "No encontrado"}), 404
    try:
        equipo.nombre = data['nombre']
        equipo.tipo = data['tipo']
        equipo.serial = data['serial']
        equipo.ubicacion = data['ubicacion']
        equipo.estado = data.get('estado', equipo.estado)
        equipo.observaciones = data.get('observaciones', '')
        equipo.cliente_id = data['cliente_id']
        db.session.commit()
        return jsonify({"mensaje": "Equipo actualizado"})
    except Exception:
        return jsonify({"mensaje": "Error al actualizar"}), 400

@app.route('/api/equipos/<int:id>', methods=['DELETE'])
@login_required
def eliminar_equipo(id):
    if current_user.username == 'invitado':
        return jsonify({"mensaje": "⚠️ Modo Invitado: Solo lectura"}), 403
    equipo = Equipo.query.get(id)
    if equipo:
        db.session.delete(equipo)
        db.session.commit()
        return jsonify({"mensaje": "Eliminado"})
    return jsonify({"mensaje": "No encontrado"}), 404

# --- PDF ---
@app.route('/exportar-pdf')
@login_required
def exportar_pdf():
    cliente_id = request.args.get('cliente_id')
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setTitle("Reporte de Mantenimiento")
    
    titulo = "Reporte Global"
    equipos = []
    if cliente_id:
        cli = Cliente.query.get(cliente_id)
        if cli:
            titulo = f"Cliente: {cli.nombre}"
            equipos = cli.equipos
    else:
        equipos = Equipo.query.all()

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 750, titulo)
    y = 700
    
    for eq in equipos:
        if y < 100:
            c.showPage()
            y = 750
        
        qr = qrcode.make(f"ID:{eq.id}-SN:{eq.serial}")
        qr_mem = io.BytesIO()
        qr.save(qr_mem, format="PNG")
        qr_mem.seek(0)
        c.drawImage(ImageReader(qr_mem), 50, y-10, 40, 40)
        
        c.setFont("Helvetica-Bold", 12)
        c.drawString(100, y+20, f"{eq.nombre} ({eq.estado})")
        c.setFont("Helvetica", 10)
        c.drawString(100, y+5, f"{eq.tipo} | SN: {eq.serial} | {eq.ubicacion}")
        y -= 60
        
    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="reporte.pdf", mimetype='application/pdf')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)