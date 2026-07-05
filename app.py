import os
import math
import requests
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, verify_jwt_in_request
from werkzeug.security import generate_password_hash, check_password_hash
import mercadopago

# ==========================================
# CONFIGURAÇÕES
# ==========================================
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
if MP_ACCESS_TOKEN:
    sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
else:
    sdk = None
    print("⚠️ MP_ACCESS_TOKEN não configurado")

app = Flask(__name__)
CORS(app, origins=["*"], methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "Authorization"])

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///rotabrasil.db")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "super-secret-key-rota-brasil")

db = SQLAlchemy(app)
jwt = JWTManager(app)
socketio = SocketIO(app, cors_allowed_origins="*", transports=['websocket', 'polling'])

# ==========================================
# CONSTANTES
# ==========================================
ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjBkNzdmNzYyMzU3YzQxZThhODJjMDNlMmJlOTJlMTNiIiwiaCI6Im11cm11cjY0In0="
BANDEIRADA = 5.0
VALOR_KM = 2.5

# ==========================================
# MODELOS (ORDEM CORRETA)
# ==========================================

class Usuario(db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)
    telefone = db.Column(db.String(20))
    tipo = db.Column(db.String(20), default="passageiro")
    foto_perfil = db.Column(db.String(255), nullable=True)
    carro = db.Column(db.String(50), nullable=True)
    placa = db.Column(db.String(20), nullable=True)
    online = db.Column(db.Boolean, default=False)
    admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'nome': self.nome, 'email': self.email,
            'telefone': self.telefone, 'tipo': self.tipo,
            'foto_perfil': self.foto_perfil, 'carro': self.carro,
            'placa': self.placa, 'online': self.online
        }

class Carteira(db.Model):
    __tablename__ = 'carteiras'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, unique=True)
    saldo = db.Column(db.Float, default=0.0)
    saldo_bloqueado = db.Column(db.Float, default=0.0)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

class Corrida(db.Model):
    __tablename__ = 'corridas'
    id = db.Column(db.Integer, primary_key=True)
    passageiro_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    motorista_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    origem = db.Column(db.String(255))
    destino = db.Column(db.String(255))
    lat_origem = db.Column(db.Float)
    lon_origem = db.Column(db.Float)
    lat_destino = db.Column(db.Float)
    lon_destino = db.Column(db.Float)
    valor = db.Column(db.Float)
    distancia = db.Column(db.String(50))
    forma_pagamento = db.Column(db.String(20), default='pix')
    status = db.Column(db.String(20), default='pendente')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Transacao(db.Model):
    __tablename__ = 'transacoes'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, nullable=False)
    tipo = db.Column(db.String(50))
    valor = db.Column(db.Float)
    descricao = db.Column(db.String(300))
    data = db.Column(db.DateTime, default=datetime.utcnow)
    payment_id = db.Column(db.String(100), unique=True, nullable=True)

class Avaliacao(db.Model):
    __tablename__ = 'avaliacoes'
    id = db.Column(db.Integer, primary_key=True)
    corrida_id = db.Column(db.Integer)
    avaliador_id = db.Column(db.Integer)
    avaliado_id = db.Column(db.Integer)
    nota = db.Column(db.Integer)
    comentario = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================

def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        usuario_id = get_jwt_identity()
        usuario = Usuario.query.get(int(usuario_id))
        if not usuario or not usuario.admin:
            return jsonify({"erro": "Acesso negado"}), 403
        return func(*args, **kwargs)
    return wrapper

def bloquear_valor_corrida(usuario_id, valor):
    """Bloqueia saldo apenas para pagamento Pix"""
    carteira = Carteira.query.filter_by(usuario_id=usuario_id).first()
    if not carteira:
        print(f"❌ Carteira não encontrada para usuário {usuario_id}")
        return False
    if carteira.saldo < valor:
        print(f"❌ Saldo insuficiente: R$ {carteira.saldo:.2f} < R$ {valor:.2f}")
        return False
    carteira.saldo -= valor
    carteira.saldo_bloqueado += valor
    db.session.commit()
    print(f"✅ Pix bloqueado: R$ {valor:.2f} | Saldo restante: R$ {carteira.saldo:.2f}")
    return True

def liberar_pagamento(passageiro_id, motorista_id, valor):
    """Libera pagamento após corrida finalizada"""
    plataforma = valor * 0.15
    motorista_recebe = valor - plataforma
    cp = Carteira.query.filter_by(usuario_id=passageiro_id).first()
    cm = Carteira.query.filter_by(usuario_id=motorista_id).first()
    if cp:
        cp.saldo_bloqueado -= valor
    if cm:
        cm.saldo += motorista_recebe
    db.session.commit()

def devolver_saldo(usuario_id, valor):
    """Devolve saldo bloqueado"""
    carteira = Carteira.query.filter_by(usuario_id=usuario_id).first()
    if carteira:
        carteira.saldo += valor
        carteira.saldo_bloqueado -= valor
        db.session.commit()

# ==========================================
# AUTENTICAÇÃO
# ==========================================

@app.route("/register", methods=["POST"])
def register():
    dados = request.get_json()
    senha_cripto = generate_password_hash(dados.get("senha"))
    
    novo = Usuario(
        nome=dados.get("nome"),
        email=dados.get("email"),
        senha=senha_cripto,
        telefone=dados.get("telefone"),
        tipo=dados.get("tipo", "passageiro"),
        foto_perfil=dados.get("foto_perfil"),
        carro=dados.get("carro"),
        placa=dados.get("placa")
    )
    db.session.add(novo)
    db.session.commit()
    
    # Cria carteira
    carteira = Carteira(usuario_id=novo.id)
    db.session.add(carteira)
    db.session.commit()
    
    return jsonify({"status": "Conta criada com sucesso!"}), 201

@app.route("/login", methods=["POST"])
def login():
    dados = request.get_json()
    usuario = Usuario.query.filter_by(email=dados.get("email")).first()
    
    if not usuario or not check_password_hash(usuario.senha, dados.get("senha")):
        return jsonify({"erro": "E-mail ou senha incorretos"}), 401
    
    token = create_access_token(identity=str(usuario.id))
    
    return jsonify({
        "token": token,
        "user": usuario.to_dict()
    }), 200

# ==========================================
# STATUS MOTORISTA
# ==========================================

@app.route("/ficar_online/<int:id>", methods=["POST"])
def ficar_online(id):
    mot = Usuario.query.get(id)
    if mot:
        mot.online = True
        db.session.commit()
    return jsonify({"status": "Motorista online"}), 200

@app.route("/ficar_offline/<int:id>", methods=["POST"])
def ficar_offline(id):
    mot = Usuario.query.get(id)
    if mot:
        mot.online = False
        db.session.commit()
    return jsonify({"status": "Motorista offline"}), 200

# ==========================================
# CARTEIRA
# ==========================================

@app.route("/carteira/saldo")
@jwt_required()
def saldo():
    usuario_id = get_jwt_identity()
    carteira = Carteira.query.filter_by(usuario_id=int(usuario_id)).first()
    if carteira:
        return jsonify({"saldo": carteira.saldo, "bloqueado": carteira.saldo_bloqueado})
    return jsonify({"saldo": 0, "bloqueado": 0})

@app.route('/carteira/historico')
@jwt_required()
def historico():
    usuario_id = get_jwt_identity()
    transacoes = Transacao.query.filter_by(usuario_id=int(usuario_id)).order_by(Transacao.data.desc()).all()
    return jsonify([{
        "tipo": t.tipo, "valor": t.valor, "descricao": t.descricao,
        "data": t.data.strftime("%d/%m/%Y %H:%M") if t.data else None
    } for t in transacoes])

# ==========================================
# CORRIDAS
# ==========================================

@app.route("/calcular_corrida", methods=["POST", "OPTIONS"])
def calcular_corrida():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    dados = request.get_json()
    lat_origem = float(dados.get("lat_origem", 0))
    lon_origem = float(dados.get("lon_origem", 0))
    lat_destino = float(dados.get("lat_destino", 0))
    lon_destino = float(dados.get("lon_destino", 0))
    
    # Tenta OpenRouteService
    try:
        url = "https://api.openrouteservice.org/v2/directions/driving-car"
        headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
        body = {"coordinates": [[lon_origem, lat_origem], [lon_destino, lat_destino]]}
        resp = requests.post(url, json=body, headers=headers, timeout=10)
        if resp.status_code == 200:
            dados_rota = resp.json()
            if dados_rota.get("routes"):
                dist_m = dados_rota["routes"][0]["summary"]["distance"]
                dist_km = dist_m / 1000
                tempo_s = dados_rota["routes"][0]["summary"]["duration"]
                tempo_min = tempo_s / 60
                valor = BANDEIRADA + (dist_km * VALOR_KM)
                return jsonify({"distancia": round(dist_km, 2), "valor": round(valor, 2), "tempo": round(tempo_min, 0), "fonte": "ORS"})
    except: pass
    
    # Tenta OSRM
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon_origem},{lat_origem};{lon_destino},{lat_destino}?overview=false"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            dados_rota = resp.json()
            if dados_rota.get("routes"):
                dist_m = dados_rota["routes"][0]["distance"]
                dist_km = dist_m / 1000
                tempo_s = dados_rota["routes"][0]["duration"]
                tempo_min = tempo_s / 60
                valor = BANDEIRADA + (dist_km * VALOR_KM)
                return jsonify({"distancia": round(dist_km, 2), "valor": round(valor, 2), "tempo": round(tempo_min, 0), "fonte": "OSRM"})
    except: pass
    
    # Fallback: Haversine
    R = 6371
    lat1, lon1 = math.radians(lat_origem), math.radians(lon_origem)
    lat2, lon2 = math.radians(lat_destino), math.radians(lon_destino)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    dist_km = R * 2 * math.asin(math.sqrt(a))
    tempo_min = (dist_km / 30) * 60
    valor = BANDEIRADA + (dist_km * VALOR_KM)
    return jsonify({"distancia": round(dist_km, 2), "valor": round(valor, 2), "tempo": round(tempo_min, 0), "fonte": "Haversine"})

@app.route("/nova_corrida", methods=["POST"])
@jwt_required()
def nova_corrida():
    passageiro_id = int(get_jwt_identity())
    passageiro = Usuario.query.get(passageiro_id)
    dados = request.get_json()
    
    valor_corrida = float(dados.get("valor", 0))
    forma_pagamento = dados.get("forma_pagamento", "pix")
    
    # 🔥 SÓ BLOQUEIA SALDO SE FOR PIX
    if forma_pagamento == "pix":
        if not bloquear_valor_corrida(passageiro_id, valor_corrida):
            return jsonify({"erro": "Saldo insuficiente! Adicione saldo ou escolha pagar em dinheiro."}), 400
    
    nova = Corrida(
        passageiro_id=passageiro_id,
        origem=dados.get("origem"),
        destino=dados.get("destino"),
        lat_origem=dados.get("lat_origem"),
        lon_origem=dados.get("lon_origem"),
        lat_destino=dados.get("lat_destino"),
        lon_destino=dados.get("lon_destino"),
        valor=valor_corrida,
        distancia=dados.get("distancia", ""),
        forma_pagamento=forma_pagamento,
        status="pendente"
    )
    db.session.add(nova)
    db.session.commit()
    
    dados_chamada = {
        "corrida_id": nova.id,
        "passageiro_id": passageiro.id,
        "passageiro_nome": passageiro.nome,
        "passageiro_telefone": passageiro.telefone or "",
        "foto_passageiro": passageiro.foto_perfil or "",
        "foto_perfil": passageiro.foto_perfil or "",
        "origem": nova.origem,
        "destino": nova.destino,
        "valor": nova.valor,
        "distancia": dados.get("distancia", "Calculando..."),
        "forma_pagamento": forma_pagamento,
        "lat_origem": dados.get("lat_origem"),
        "lon_origem": dados.get("lon_origem"),
        "lat_destino": dados.get("lat_destino"),
        "lon_destino": dados.get("lon_destino")
    }
    
    motoristas = Usuario.query.filter_by(tipo="motorista", online=True).all()
    for m in motoristas:
        socketio.emit("nova_corrida", dados_chamada, room=f"motorista_{m.id}")
    socketio.emit("nova_corrida", dados_chamada)
    
    print(f"🆕 Corrida #{nova.id} | 💰 {forma_pagamento} | R$ {valor_corrida:.2f}")
    
    return jsonify({"status": "Procurando motoristas", "corrida_id": nova.id, "forma_pagamento": forma_pagamento}), 201

@app.route('/aceitar_corrida/<int:id>', methods=['POST'])
@jwt_required()
def aceitar_corrida(id):
    motorista_id = int(get_jwt_identity())
    motorista = Usuario.query.get(motorista_id)
    corrida = Corrida.query.get(id)
    
    if not corrida:
        return jsonify({"erro": "Corrida não encontrada"}), 404
    if corrida.status != "pendente":
        return jsonify({"erro": "Corrida já aceita"}), 400
    
    corrida.motorista_id = motorista.id
    corrida.status = "aceita"
    db.session.commit()
    
    dados_socket = {
        "corrida_id": corrida.id,
        "motorista_id": motorista.id,
        "motorista_nome": motorista.nome,
        "motorista_foto": motorista.foto_perfil,
        "carro": motorista.carro,
        "placa": motorista.placa
    }
    
    socketio.emit("corrida_aceita", dados_socket, room=f"corrida_{id}")
    return jsonify({"sucesso": True, "corrida_id": corrida.id, "status": "aceita"}), 200

@app.route("/cancelar_corrida/<int:id>", methods=["POST"])
@jwt_required()
def cancelar_corrida(id):
    corrida = Corrida.query.get(id)
    
    if not corrida:
        return jsonify({"sucesso": False, "erro": "Corrida não encontrada"}), 404
    if corrida.status in ["finalizada", "cancelada"]:
        return jsonify({"sucesso": False, "erro": "Corrida já finalizada/cancelada"}), 400
    
    try:
        corrida.status = "cancelada"
        # 🔥 SÓ DEVOLVE SALDO SE FOR PIX
        if corrida.forma_pagamento == 'pix':
            devolver_saldo(corrida.passageiro_id, corrida.valor)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    
    socketio.emit("corrida_cancelada", {"corrida_id": id}, room=f"corrida_{id}")
    return jsonify({"sucesso": True, "corrida_id": corrida.id}), 200

@app.route("/cancelar_corrida_motorista/<int:id>", methods=["POST"])
def cancelar_corrida_motorista(id):
    corrida = Corrida.query.get(id)
    if corrida:
        corrida.status = "cancelada"
        # 🔥 SÓ DEVOLVE SALDO SE FOR PIX
        if corrida.forma_pagamento == 'pix':
            devolver_saldo(corrida.passageiro_id, corrida.valor)
        db.session.commit()
        socketio.emit("corrida_cancelada", {"corrida_id": id}, room=f"corrida_{id}")
    return jsonify({"status": "cancelada"}), 200

@app.route('/finalizar_corrida/<int:corrida_id>', methods=['POST'])
def finalizar_corrida(corrida_id):
    dados = request.get_json() or {}
    corrida = Corrida.query.get(corrida_id)
    
    if not corrida:
        return jsonify({"sucesso": False, "erro": "Corrida não encontrada"}), 404
    
    corrida.status = "finalizada"
    
    # 🔥 SÓ LIBERA PAGAMENTO SE FOR PIX
    if corrida.forma_pagamento == 'pix':
        liberar_pagamento(corrida.passageiro_id, corrida.motorista_id, corrida.valor)
    
    registro = Transacao(
        usuario_id=corrida.passageiro_id,
        tipo="corrida",
        valor=corrida.valor,
        descricao=f"Corrida #{corrida.id} - {'💵 Dinheiro' if corrida.forma_pagamento == 'dinheiro' else '💳 Pix'}"
    )
    db.session.add(registro)
    db.session.commit()
    
    socketio.emit('viagem_finalizada', {
        "corrida_id": corrida_id,
        "valor": corrida.valor,
        "motorista_nome": dados.get('motorista_nome', 'Motorista'),
        "motorista_id": corrida.motorista_id
    }, room=f"corrida_{corrida_id}")
    
    return jsonify({"sucesso": True, "valor": corrida.valor})

# ==========================================
# LOCALIZAÇÃO
# ==========================================

@app.route("/localizacao_motorista/<int:corrida_id>", methods=["GET"])
def get_localizacao_motorista(corrida_id):
    # Busca a última localização (se tiver tabela)
    return jsonify({"corrida_id": corrida_id, "lat": None, "lng": None})

@app.route("/atualizar_localizacao", methods=["POST"])
@jwt_required()
def atualizar_localizacao():
    motorista_id = get_jwt_identity()
    dados = request.get_json()
    socketio.emit("atualizacao_localizacao", dados, room=f"corrida_{dados.get('corrida_id')}")
    return jsonify({"status": "Localização atualizada"}), 200

# ==========================================
# AVALIAÇÃO
# ==========================================

@app.route("/avaliar", methods=["POST"])
@jwt_required()
def avaliar():
    user_id = int(get_jwt_identity())
    dados = request.get_json()
    avaliacao = Avaliacao(
        corrida_id=dados.get("corrida_id"),
        avaliador_id=user_id,
        avaliado_id=dados.get("motorista_id") or dados.get("passageiro_id"),
        nota=dados.get("nota"),
        comentario=dados.get("comentario")
    )
    db.session.add(avaliacao)
    db.session.commit()
    return jsonify({"status": "avaliado"})

@app.route("/avaliacoes", methods=["GET"])
def get_avaliacoes():
    usuario_id = request.args.get("usuario_id")
    if usuario_id:
        avaliacoes = Avaliacao.query.filter_by(avaliado_id=int(usuario_id)).order_by(Avaliacao.created_at.desc()).limit(10).all()
    else:
        avaliacoes = Avaliacao.query.order_by(Avaliacao.created_at.desc()).limit(20).all()
    
    lista = []
    for a in avaliacoes:
        avaliador = Usuario.query.get(a.avaliador_id)
        lista.append({
            "nota": a.nota,
            "comentario": a.comentario,
            "nome_avaliador": avaliador.nome if avaliador else "Usuário"
        })
    return jsonify({"avaliacoes": lista})

# ==========================================
# PIX / MERCADO PAGO
# ==========================================

@app.route("/checkout/criar", methods=["POST"])
@jwt_required()
def criar_checkout():
    if not sdk:
        return jsonify({"erro": "Mercado Pago não configurado"}), 500
    
    dados = request.get_json()
    valor = float(dados["valor"])
    usuario_id = get_jwt_identity()
    
    preference_data = {
        "items": [{"title": "Recarga Carteira Rota Brasil", "quantity": 1, "unit_price": valor}],
        "external_reference": str(usuario_id),
        "notification_url": "https://rotabrasil-tobu.onrender.com/webhook"
    }
    
    preference = sdk.preference().create(preference_data)
    response = preference.get("response", {})
    link = response.get("init_point") or response.get("sandbox_init_point")
    
    return jsonify({"link": link})

@app.route("/webhook", methods=["POST"])
def webhook():
    if not sdk:
        return "OK", 200
    
    data = request.get_json()
    payment_id = data.get("data", {}).get("id")
    
    if not payment_id:
        return "OK", 200
    
    payment = sdk.payment().get(payment_id)
    info = payment["response"]
    status = info.get("status")
    
    if status == "approved":
        usuario_id = int(info["external_reference"])
        valor = float(info["transaction_amount"])
        
        if Transacao.query.filter_by(payment_id=str(payment_id)).first():
            return "OK", 200
        
        carteira = Carteira.query.filter_by(usuario_id=usuario_id).first()
        if carteira:
            carteira.saldo += valor
            transacao = Transacao(
                usuario_id=usuario_id, tipo="recarga", valor=valor,
                descricao=f"Recarga Mercado Pago ({payment_id})", payment_id=str(payment_id)
            )
            db.session.add(transacao)
            db.session.commit()
    
    return "OK", 200

# ==========================================
# ADMIN
# ==========================================

@app.route('/admin/dashboard', methods=['GET'])
def admin_dashboard():
    usuarios = Usuario.query.count()
    corridas = Corrida.query.count()
    motoristas_online = Usuario.query.filter_by(tipo='motorista', online=True).count()
    saldo_total = db.session.query(db.func.sum(Carteira.saldo)).scalar() or 0
    
    conn = db.engine.connect()
    motoristas = db.session.execute(db.text("""
        SELECT DISTINCT u.id, u.nome, u.carro, u.placa, u.nota_media
        FROM usuarios u WHERE u.tipo = 'motorista' AND u.online = 1
    """)).fetchall()
    
    corridas_ativas = db.session.execute(db.text("""
        SELECT c.*, p.nome as passageiro_nome, m.nome as motorista_nome, m.carro, m.placa
        FROM corridas c
        LEFT JOIN usuarios p ON c.passageiro_id = p.id
        LEFT JOIN usuarios m ON c.motorista_id = m.id
        WHERE c.status IN ('pendente', 'aceita')
        ORDER BY c.created_at DESC
    """)).fetchall()
    
    corridas_finalizadas = db.session.execute(db.text("""
        SELECT c.*, p.nome as passageiro_nome, m.nome as motorista_nome
        FROM corridas c
        LEFT JOIN usuarios p ON c.passageiro_id = p.id
        LEFT JOIN usuarios m ON c.motorista_id = m.id
        WHERE c.status = 'finalizada'
        ORDER BY c.created_at DESC LIMIT 20
    """)).fetchall()
    
    return jsonify({
        'usuarios': usuarios,
        'corridas': corridas,
        'motoristas_online': motoristas_online,
        'saldo_total': float(saldo_total),
        'motoristas_online_lista': [dict(m) for m in motoristas],
        'corridas_ativas': [dict(c) for c in corridas_ativas],
        'corridas_finalizadas': [dict(c) for c in corridas_finalizadas]
    })

# ==========================================
# SOCKET.IO
# ==========================================

@socketio.on("connect")
def on_connect():
    print(f"✅ Cliente conectado: {request.sid}")

@socketio.on("disconnect")
def on_disconnect():
    print(f"❌ Cliente desconectado: {request.sid}")

@socketio.on('entrar_na_sala')
def entrar_na_sala(dados):
    cid = dados.get('corrida_id')
    if cid:
        join_room(f"corrida_{cid}")
        print(f"🏠 Entrou na sala corrida_{cid}")

@socketio.on("motorista_online")
def motorista_online(dados):
    motorista_id = dados.get("id")
    if motorista_id:
        join_room(f"motorista_{motorista_id}")
        print(f"🟢 Motorista {motorista_id} online")

@socketio.on("localizacao_motorista")
def receber_localizacao(dados):
    corrida_id = dados.get('corrida_id')
    if corrida_id:
        socketio.emit("localizacao_motorista", {
            "corrida_id": corrida_id,
            "motorista_id": dados.get("motorista_id"),
            "lat": dados.get("lat"),
            "lng": dados.get("lng"),
            "motorista_nome": dados.get("motorista_nome", ""),
            "motorista_foto": dados.get("motorista_foto", "")
        }, room=f"corrida_{corrida_id}")
        print(f"📍 Localização corrida {corrida_id}")

@socketio.on('corrida_aceita')
def handle_corrida_aceita(dados):
    cid = dados.get('corrida_id')
    if cid:
        socketio.emit('corrida_aceita', dados, room=f"corrida_{cid}")

@socketio.on('viagem_iniciada')
def handle_viagem_iniciada(dados):
    cid = dados.get('corrida_id')
    if cid:
        socketio.emit('viagem_iniciada', dados, room=f"corrida_{cid}")

@socketio.on('viagem_finalizada')
def handle_viagem_finalizada(dados):
    cid = dados.get('corrida_id')
    if cid:
        socketio.emit('viagem_finalizada', dados, room=f"corrida_{cid}")

@socketio.on('cancelar_corrida')
def handle_cancelar_corrida(dados):
    cid = dados.get('corrida_id')
    if cid:
        socketio.emit('corrida_cancelada', {'corrida_id': cid}, room=f"corrida_{cid}")

@socketio.on('corrida_cancelada_motorista')
def handle_cancelar_motorista(dados):
    cid = dados.get('corrida_id')
    if cid:
        socketio.emit('corrida_cancelada', {'corrida_id': cid}, room=f"corrida_{cid}")

# ==========================================
# RECRIAR BANCO
# ==========================================

@app.route("/recriar")
def recriar():
    try:
        with app.app_context():
            db.session.execute(db.text("DROP TABLE IF EXISTS avaliacoes CASCADE"))
            db.session.execute(db.text("DROP TABLE IF EXISTS transacoes CASCADE"))
            db.session.execute(db.text("DROP TABLE IF EXISTS corridas CASCADE"))
            db.session.execute(db.text("DROP TABLE IF EXISTS carteiras CASCADE"))
            db.session.execute(db.text("DROP TABLE IF EXISTS usuarios CASCADE"))
            db.session.commit()
            db.create_all()
        return jsonify({"status": "✅ Banco recriado com sucesso!"})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# ==========================================
# ROTAS BÁSICAS
# ==========================================

@app.route("/")
def home():
    return jsonify({"status": "online", "api": "Rota Brasil"})

@app.route("/teste")
def teste():
    return jsonify({"status": "online", "mensagem": "API Rota Brasil funcionando!"})

# ==========================================
# INICIAR
# ==========================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
