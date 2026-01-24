import os
from datetime import datetime
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
import base64 
import pytz

app = Flask(__name__)
app.secret_key = 'super_secreto_clave_segura_gnb'

# --- CONFIGURACIÓN BD ---
database_url = os.environ.get('DATABASE_URL')
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
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
    foto = db.Column(db.Text, nullable=True) 
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    mantenimientos = db.relationship('Mantenimiento', backref='equipo_rel', lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'tipo': self.tipo,
            'serial': self.serial,
            'ubicacion': self.ubicacion,
            'estado': self.estado,
            'observaciones': self.observaciones,
            'foto': self.foto,
            'cliente_id': self.cliente_id
        }

class Mantenimiento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=lambda: datetime.now(pytz.timezone('America/Bogota')))
    descripcion = db.Column(db.String(500), nullable=False)
    usuario = db.Column(db.String(100), nullable=False)
    equipo_id = db.Column(db.Integer, db.ForeignKey('equipo.id'), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'fecha': self.fecha.strftime('%Y-%m-%d %H:%M'),
            'descripcion': self.descripcion,
            'usuario': self.usuario,
            'equipo_id': self.equipo_id
        }

# --- RUTAS VISTAS ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
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
    flash("Error: Ejecuta /setup-fase2 primero")
    return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    cliente_id = request.args.get('cliente_id')
    clientes = Cliente.query.all()
    equipos = Equipo.query.filter_by(cliente_id=cliente_id).all() if cliente_id else Equipo.query.all()
    cliente_actual = Cliente.query.get(cliente_id) if cliente_id else None
    return render_template('index.html', equipos=equipos, clientes=clientes, cliente_actual=cliente_actual, user=current_user)

# --- SETUP ---
@app.route('/setup-fase2')
def setup_db():
    try:
        with app.app_context():
            db.create_all()
            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin'); admin.set_password('admin123'); db.session.add(admin)
            if not User.query.filter_by(username='invitado').first():
                guest = User(username='invitado'); guest.set_password('invitado'); db.session.add(guest)
            if not Cliente.query.first():
                db.session.add(Cliente(nombre="Cliente Demo 1", direccion="Sede Principal"))
            db.session.commit()
            return "✅ SETUP COMPLETO."
    except Exception as e:
        return f"❌ Error: {str(e)}"

# --- API ---
@app.route('/api/usuarios', methods=['GET'])
@login_required
def obtener_usuarios():
    if current_user.username == 'invitado': return jsonify({"mensaje": "Denegado"}), 403
    return jsonify([{"id": u.id, "username": u.username} for u in User.query.all()])

@app.route('/api/usuarios', methods=['POST'])
@login_required
def crear_usuario():
    if current_user.username == 'invitado': return jsonify({"mensaje": "Denegado"}), 403
    data = request.json
    if User.query.filter_by(username=data['username']).first(): return jsonify({"mensaje": "Existe"}), 400
    nuevo = User(username=data['username'])
    nuevo.set_password(data['password'])
    db.session.add(nuevo)
    db.session.commit()
    return jsonify({"mensaje": "Creado"})

@app.route('/api/usuarios/<int:id>', methods=['DELETE'])
@login_required
def eliminar_usuario(id):
    if current_user.username == 'invitado': return jsonify({"mensaje": "Denegado"}), 403
    if current_user.id == id: return jsonify({"mensaje": "No puedes borrarte a ti mismo"}), 400
    user = User.query.get(id)
    if user and user.username not in ['admin', 'invitado']:
        db.session.delete(user)
        db.session.commit()
        return jsonify({"mensaje": "Eliminado"})
    return jsonify({"mensaje": "No permitido"}), 400

@app.route('/api/clientes', methods=['POST'])
@login_required
def crear_cliente():
    if current_user.username == 'invitado': return jsonify({"mensaje": "Denegado"}), 403
    db.session.add(Cliente(nombre=request.json['nombre'], direccion=request.json.get('direccion','')))
    db.session.commit()
    return jsonify({"mensaje": "Ok"})

@app.route('/api/equipos', methods=['POST'])
@login_required
def agregar_equipo():
    if current_user.username == 'invitado': return jsonify({"mensaje": "Solo lectura"}), 403
    data = request.json
    try:
        nuevo = Equipo(
            cliente_id=data['cliente_id'],
            nombre=data['nombre'], 
            tipo=data['tipo'], 
            serial=data['serial'], 
            ubicacion=data['ubicacion'],
            estado=data.get('estado', 'Operativo'),
            observaciones=data.get('observaciones', ''),
            foto=data.get('foto', '')
        )
        db.session.add(nuevo)
        db.session.commit()
        return jsonify({"mensaje": "Equipo registrado"})
    except Exception as e:
        return jsonify({"mensaje": "Error: Serial duplicado o datos inválidos"}), 400

@app.route('/api/equipos/<int:id>', methods=['PUT'])
@login_required
def editar_equipo(id):
    if current_user.username == 'invitado': return jsonify({"mensaje": "Solo lectura"}), 403
    data = request.json
    equipo = Equipo.query.get(id)
    if not equipo: return jsonify({"mensaje": "No encontrado"}), 404
    
    equipo.nombre = data['nombre']
    equipo.tipo = data['tipo']
    equipo.serial = data['serial']
    equipo.ubicacion = data['ubicacion']
    equipo.estado = data.get('estado', equipo.estado)
    equipo.observaciones = data.get('observaciones', '')
    equipo.cliente_id = data['cliente_id']
    if data.get('foto'): equipo.foto = data['foto']

    db.session.commit()
    return jsonify({"mensaje": "Actualizado"})

@app.route('/api/equipos/<int:id>', methods=['DELETE'])
@login_required
def eliminar_equipo(id):
    if current_user.username == 'invitado': return jsonify({"mensaje": "Solo lectura"}), 403
    eq = Equipo.query.get(id)
    if eq: db.session.delete(eq); db.session.commit(); return jsonify({"mensaje": "Eliminado"})
    return jsonify({"mensaje": "No encontrado"}), 404

@app.route('/api/mantenimientos', methods=['POST'])
@login_required
def agregar_mant():
    if current_user.username == 'invitado': return jsonify({"mensaje": "Denegado"}), 403
    db.session.add(Mantenimiento(descripcion=request.json['descripcion'], usuario=current_user.username, equipo_id=request.json['equipo_id']))
    db.session.commit()
    return jsonify({"mensaje": "Ok"})

@app.route('/api/mantenimientos/<int:id>', methods=['GET'])
@login_required
def ver_mant(id):
    return jsonify([m.to_dict() for m in Mantenimiento.query.filter_by(equipo_id=id).order_by(Mantenimiento.fecha.desc()).all()])

# --- PDF (CORREGIDO: Títulos Dinámicos + Fotos) ---
@app.route('/exportar-pdf')
@login_required
def exportar_pdf():
    cliente_id = request.args.get('cliente_id')
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setTitle("Reporte de Mantenimiento")

    # --- LÓGICA DE TÍTULOS RESTAURADA ---
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

    # --- ENCABEZADO MEJORADO ---
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 750, titulo_reporte)
    c.setFont("Helvetica", 12)
    c.drawString(50, 735, subtitulo)
    c.line(50, 725, 550, 725) # Línea separadora
    
    y = 670
    
    for eq in equipos:
        if y < 100: c.showPage(); y = 750
        
        # QR
        qr = qrcode.make(f"ID:{eq.id}-SN:{eq.serial}")
        qr_mem = io.BytesIO(); qr.save(qr_mem, format="PNG"); qr_mem.seek(0)
        c.drawImage(ImageReader(qr_mem), 50, y-10, 40, 40)
        
        # Textos
        c.setFont("Helvetica-Bold", 12)
        c.drawString(100, y+20, eq.nombre)
        c.setFont("Helvetica", 10)
        
        # Indicador de foto
        texto_extra = " (Con Foto)" if eq.foto else ""
        c.drawString(100, y+5, f"{eq.tipo} | SN: {eq.serial} {texto_extra}")
        
        # Estado (Color)
        if eq.estado == 'Falla': c.setFillColor(colors.red)
        else: c.setFillColor(colors.green)
        c.drawString(450, y+20, eq.estado)
        c.setFillColor(colors.black)

        y -= 60

    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="reporte.pdf", mimetype='application/pdf')

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)