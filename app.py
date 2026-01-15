from flask import Flask, render_template, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
import qrcode
import io
import os

app = Flask(__name__)

# --- CONFIGURACIÓN DE BASE DE DATOS ---
# Usamos SQLite local. En Render se borrará al reiniciar, 
# pero el script /setup-fase2 la regenerará.
# --- CONFIGURACIÓN DE BASE DE DATOS INTELIGENTE ---
# Intentamos leer la variable de Render
database_url = os.environ.get('DATABASE_URL')

if database_url:
    # Si estamos en Render, usamos Postgres (con corrección del nombre)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Si estamos en tu PC, usamos SQLite local
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mantenimiento_v2.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- MODELOS (TABLAS) ---
class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    direccion = db.Column(db.String(200), nullable=True)
    # Relación: Un cliente tiene muchos equipos
    equipos = db.relationship('Equipo', backref='cliente', lazy=True)

class Equipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
    serial = db.Column(db.String(50), unique=True, nullable=False)
    ubicacion = db.Column(db.String(100), nullable=False)
    estado = db.Column(db.String(20), default="Operativo")
    observaciones = db.Column(db.String(300), nullable=True) # Campo nuevo
    # Llave foránea: A quién pertenece este equipo
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)

# --- RUTA DE INSTALACIÓN (SETUP) ---
# ¡ESTA ES LA QUE TE FALTABA PARA RENDER!
@app.route('/setup-fase2')
def setup_db():
    try:
        with app.app_context():
            db.create_all() # Crea las tablas vacías
            
            # Verificamos si ya existen clientes para no duplicar
            if not Cliente.query.first():
                # Creamos los clientes base
                c1 = Cliente(nombre="GNB Sudameris - Torre A", direccion="Calle 72")
                c2 = Cliente(nombre="Edificio Avianca", direccion="Calle 26")
                db.session.add(c1)
                db.session.add(c2)
                db.session.commit()
                return "✅ Base de datos creada y Clientes Iniciales (GNB/Avianca) listos!"
            return "⚠️ La base de datos ya existe. No se hicieron cambios."
    except Exception as e:
        return f"❌ Error al configurar DB: {str(e)}"

# --- RUTAS PRINCIPALES ---
@app.route('/')
def dashboard():
    # 1. Filtro
    cliente_id_filtrado = request.args.get('cliente_id')
    
    # 2. Obtener clientes para el selector
    todos_los_clientes = Cliente.query.all()
    
    # 3. Lógica de selección
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
        return jsonify({"mensaje": "Equipo registrado en el edificio seleccionado"})
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
        return jsonify({"mensaje": "Equipo actualizado correctamente"})
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

# --- EXPORTAR PDF (CORREGIDO) ---
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

    # Encabezado
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 750, titulo_reporte)
    c.setFont("Helvetica", 12)
    c.drawString(50, 735, subtitulo)
    c.setStrokeColor(colors.black)
    c.line(50, 725, 550, 725)

    y = 660  # Altura inicial ajustada
    
    for equipo in equipos:
        if y < 100:
            c.showPage()
            c.setFont("Helvetica-Bold", 10)
            c.drawString(50, 750, f"Continuación: {titulo_reporte}")
            c.line(50, 740, 550, 740)
            y = 700

        # QR
        contenido_qr = f"ID:{equipo.id}\nSN:{equipo.serial}"
        qr = qrcode.QRCode(box_size=5, border=1)
        qr.add_data(contenido_qr)
        qr.make(fit=True)
        img_qr = qr.make_image(fill_color="black", back_color="white")
        qr_buffer = io.BytesIO()
        img_qr.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        c.drawImage(ImageReader(qr_buffer), 50, y, width=50, height=50)

        # Textos
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

        # Estado
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