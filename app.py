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
class Configuracao(db.Model):
    __tablename__ = 'configuracoes'
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(50), unique=True, nullable=False)
    valor = db.Column(db.Float, nullable=False)
    descricao = db.Column(db.String(200))
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
        response = jsonify({"status": "ok"})
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization")
        return response
    
    try:
        dados = request.get_json()
        lat_origem = float(dados["lat_origem"])
        lon_origem = float(dados["lon_origem"])
        lat_destino = float(dados["lat_destino"])
        lon_destino = float(dados["lon_destino"])
        
        # --- Cálculo da distância (seu código existente) ---
        # Tenta OpenRouteService, OSRM, fallback Haversine...
        distancia_km = 0
        tempo_minutos = 0
        fonte = "Haversine"
        try:
            url = "https://api.openrouteservice.org/v2/directions/driving-car"
            headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
            body = {"coordinates": [[lon_origem, lat_origem], [lon_destino, lat_destino]]}
            response = requests.post(url, json=body, headers=headers, timeout=10)
            if response.status_code == 200:
                dados_rota = response.json()
                if dados_rota.get("routes"):
                    distancia_metros = dados_rota["routes"][0]["summary"]["distance"]
                    distancia_km = distancia_metros / 1000
                    tempo_segundos = dados_rota["routes"][0]["summary"]["duration"]
                    tempo_minutos = tempo_segundos / 60
                    fonte = "ORS"
        except:
            pass
        
        if distancia_km == 0:
            try:
                url = f"http://router.project-osrm.org/route/v1/driving/{lon_origem},{lat_origem};{lon_destino},{lat_destino}?overview=false"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    dados_rota = resp.json()
                    if dados_rota.get("routes"):
                        distancia_metros = dados_rota["routes"][0]["distance"]
                        distancia_km = distancia_metros / 1000
                        tempo_segundos = dados_rota["routes"][0]["duration"]
                        tempo_minutos = tempo_segundos / 60
                        fonte = "OSRM"
            except:
                pass
        
        if distancia_km == 0:
            # Haversine
            R = 6371
            lat1, lon1, lat2, lon2 = map(math.radians, [lat_origem, lon_origem, lat_destino, lon_destino])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
            distancia_km = R * 2 * math.asin(math.sqrt(a))
            tempo_minutos = (distancia_km / 30) * 60
        
        # 🔥 Busca as configurações do banco
        configs = Configuracao.query.all()
        config_dict = {c.chave: c.valor for c in configs}
        
        bandeirada = config_dict.get('bandeirada', 5.0)
        preco_km = config_dict.get('preco_km', 2.5)
        multiplicador = config_dict.get('multiplicador_dinamico', 1.0)
        dinamico_ativo = int(config_dict.get('dinamico_ativo', 0))
        
        # Calcula o valor
        valor = bandeirada + (distancia_km * preco_km)
        if dinamico_ativo == 1 and multiplicador > 1.0:
            valor *= multiplicador
        
        return jsonify({
            "distancia": round(distancia_km, 2),
            "valor": round(valor, 2),
            "tempo": round(tempo_minutos, 0),
            "fonte": fonte,
            "dinamico_ativo": dinamico_ativo == 1,
            "multiplicador": multiplicador if dinamico_ativo == 1 else 1.0,
            "bandeirada": bandeirada,
            "preco_km": preco_km
        })
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route("/nova_corrida", methods=["POST"])
@jwt_required()
def nova_corrida():
    passageiro_id = int(get_jwt_identity())
    passageiro = Usuario.query.get(passageiro_id)
    dados = request.get_json()
    
    valor_corrida = float(dados.get("valor", 0))
    forma_pagamento = dados.get("forma_pagamento", "pix")
    paradas = dados.get("paradas", [])  # 🔥 RECEBE AS PARADAS
    
    if forma_pagamento == "pix":
        if not bloquear_valor_corrida(passageiro_id, valor_corrida):
            return jsonify({"erro": "Saldo insuficiente!"}), 400
    
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
    
    # 🔥 DADOS COMPLETOS COM PARADAS
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
        "lon_destino": dados.get("lon_destino"),
        "paradas": paradas  # 🔥 ENVIA AS PARADAS PARA O MOTORISTA
    }
    
    motoristas = Usuario.query.filter_by(tipo="motorista", online=True).all()
    for m in motoristas:
        socketio.emit("nova_corrida", dados_chamada, room=f"motorista_{m.id}")
    socketio.emit("nova_corrida", dados_chamada)
    
    print(f"🆕 Corrida #{nova.id} | 💰 {forma_pagamento} | R$ {valor_corrida:.2f} | Paradas: {len(paradas)}")
    
    return jsonify({
        "status": "Procurando motoristas",
        "corrida_id": nova.id,
        "forma_pagamento": forma_pagamento,
        "paradas": paradas
    }), 201
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
    valor = float(dados.get("valor", 0))
    usuario_id = get_jwt_identity()
    
    if valor <= 0:
        return jsonify({"erro": "Valor inválido"}), 400
    
    try:
        preference_data = {
            "items": [
                {
                    "title": "Recarga Carteira Rota Brasil",
                    "quantity": 1,
                    "unit_price": valor
                }
            ],
            "external_reference": str(usuario_id),
            "notification_url": "https://rotabrasil-tobu.onrender.com/webhook",
            "back_urls": {
                "success": "https://rotabrasil-tobu.onrender.com/sucesso",
                "failure": "https://rotabrasil-tobu.onrender.com/falha",
                "pending": "https://rotabrasil-tobu.onrender.com/pendente"
            },
            "auto_return": "approved"
        }
        
        preference = sdk.preference().create(preference_data)
        response = preference.get("response", {})
        
        link = response.get("init_point") or response.get("sandbox_init_point")
        
        if link:
            print(f"✅ Link de pagamento gerado: {link}")
            return jsonify({"link": link})
        else:
            print(f"❌ Erro Mercado Pago: {response}")
            return jsonify({"erro": "Erro ao gerar link de pagamento", "detalhes": str(response)}), 500
            
    except Exception as e:
        print(f"❌ Erro Mercado Pago: {e}")
        return jsonify({"erro": f"Erro no Mercado Pago: {str(e)}"}), 500

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

# ==========================================
# ROTAS DO PAINEL ADMIN
# ==========================================

@app.route('/admin/motoristas', methods=['GET'])
def admin_motoristas():
    """Lista todos os motoristas"""
    try:
        motoristas = Usuario.query.filter_by(tipo='motorista').all()
        return jsonify([{
            'id': m.id,
            'nome': m.nome,
            'email': m.email,
            'telefone': m.telefone or '',
            'foto_perfil': m.foto_perfil or '',
            'carro': m.carro or '',
            'placa': m.placa or '',
            'online': m.online or False
        } for m in motoristas])
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/passageiros', methods=['GET'])
def admin_passageiros():
    """Lista todos os passageiros"""
    try:
        passageiros = Usuario.query.filter_by(tipo='passageiro').all()
        return jsonify([{
            'id': p.id,
            'nome': p.nome,
            'email': p.email,
            'telefone': p.telefone or '',
            'foto_perfil': p.foto_perfil or ''
        } for p in passageiros])
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/corridas', methods=['GET'])
def admin_corridas():
    """Lista todas as corridas"""
    try:
        corridas = Corrida.query.order_by(Corrida.id.desc()).all()
        lista = []
        for c in corridas:
            passageiro = Usuario.query.get(c.passageiro_id) if c.passageiro_id else None
            motorista = Usuario.query.get(c.motorista_id) if c.motorista_id else None
            lista.append({
                'id': c.id,
                'passageiro_nome': passageiro.nome if passageiro else 'N/A',
                'motorista_nome': motorista.nome if motorista else 'Aguardando',
                'origem': c.origem or '',
                'destino': c.destino or '',
                'valor': c.valor or 0,
                'forma_pagamento': c.forma_pagamento or 'pix',
                'status': c.status or 'pendente',
                'data_criacao': c.created_at.strftime('%d/%m/%Y %H:%M') if c.created_at else ''
            })
        return jsonify(lista)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/corridas/recentes', methods=['GET'])
def admin_corridas_recentes():
    """Últimas 10 corridas"""
    try:
        corridas = Corrida.query.order_by(Corrida.id.desc()).limit(10).all()
        lista = []
        for c in corridas:
            passageiro = Usuario.query.get(c.passageiro_id) if c.passageiro_id else None
            motorista = Usuario.query.get(c.motorista_id) if c.motorista_id else None
            lista.append({
                'id': c.id,
                'passageiro_nome': passageiro.nome if passageiro else 'N/A',
                'motorista_nome': motorista.nome if motorista else 'N/A',
                'valor': c.valor or 0,
                'status': c.status or 'pendente',
                'data_criacao': c.created_at.strftime('%d/%m/%Y %H:%M') if c.created_at else ''
            })
        return jsonify(lista)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/avaliacoes', methods=['GET'])
def admin_avaliacoes():
    """Lista todas as avaliações"""
    try:
        avaliacoes = Avaliacao.query.order_by(Avaliacao.id.desc()).all()
        return jsonify([{
            'id': a.id,
            'corrida_id': a.corrida_id,
            'avaliador_id': a.avaliador_id,
            'avaliado_id': a.avaliado_id,
            'nota': a.nota,
            'comentario': a.comentario or ''
        } for a in avaliacoes])
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/transacoes', methods=['GET'])
def listar_transacoes():
    """Lista todas as transações"""
    try:
        transacoes = Transacao.query.order_by(Transacao.data.desc()).all()
        return jsonify([{
            'id': t.id,
            'usuario_id': t.usuario_id,
            'tipo': t.tipo or '',
            'valor': t.valor or 0,
            'descricao': t.descricao or '',
            'data': t.data.strftime('%d/%m/%Y %H:%M') if t.data else ''
        } for t in transacoes])
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/excluir_motorista/<int:id>', methods=['DELETE'])
def admin_excluir_motorista(id):
    """Exclui um motorista"""
    try:
        motorista = Usuario.query.get(id)
        if not motorista:
            return jsonify({'erro': 'Motorista não encontrado'}), 404
        
        # Excluir dados relacionados
        Carteira.query.filter_by(usuario_id=id).delete()
        Transacao.query.filter_by(usuario_id=id).delete()
        Avaliacao.query.filter((Avaliacao.avaliador_id == id) | (Avaliacao.avaliado_id == id)).delete()
        Corrida.query.filter_by(motorista_id=id).update({Corrida.motorista_id: None})
        
        db.session.delete(motorista)
        db.session.commit()
        return jsonify({'status': 'Motorista excluído'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/excluir_passageiro/<int:id>', methods=['DELETE'])
def admin_excluir_passageiro(id):
    """Exclui um passageiro"""
    try:
        passageiro = Usuario.query.get(id)
        if not passageiro:
            return jsonify({'erro': 'Passageiro não encontrado'}), 404
        
        Carteira.query.filter_by(usuario_id=id).delete()
        Transacao.query.filter_by(usuario_id=id).delete()
        Avaliacao.query.filter((Avaliacao.avaliador_id == id) | (Avaliacao.avaliado_id == id)).delete()
        
        db.session.delete(passageiro)
        db.session.commit()
        return jsonify({'status': 'Passageiro excluído'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/adicionar_saldo/<int:id>', methods=['POST'])
def admin_adicionar_saldo(id):
    """Adiciona saldo a um usuário"""
    try:
        dados = request.get_json()
        valor = float(dados.get('valor', 0))
        
        if valor <= 0:
            return jsonify({'erro': 'Valor deve ser maior que zero'}), 400
        
        usuario = Usuario.query.get(id)
        if not usuario:
            return jsonify({'erro': 'Usuário não encontrado'}), 404
        
        carteira = Carteira.query.filter_by(usuario_id=id).first()
        if not carteira:
            carteira = Carteira(usuario_id=id, saldo=0, saldo_bloqueado=0)
            db.session.add(carteira)
        
        carteira.saldo += valor
        
        transacao = Transacao(
            usuario_id=id,
            tipo='credito',
            valor=valor,
            descricao=f'Adicionado pelo admin: R$ {valor:.2f}'
        )
        db.session.add(transacao)
        db.session.commit()
        
        return jsonify({'status': 'Saldo adicionado', 'novo_saldo': carteira.saldo})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/dashboard2', methods=['GET'])
def admin_dashboard2():
    """Dashboard simplificado"""
    try:
        usuarios = Usuario.query.count()
        corridas = Corrida.query.count()
        motoristas_online = Usuario.query.filter_by(tipo='motorista', online=True).count()
        saldo_total = db.session.query(db.func.sum(Carteira.saldo)).scalar() or 0
        
        return jsonify({
            'usuarios': usuarios,
            'corridas': corridas,
            'motoristas_online': motoristas_online,
            'saldo_total': float(saldo_total)
        })
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

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
@app.route('/admin/dashboard', methods=['GET'])
def admin_dashboard():
    """Retorna dados para o painel de controle"""
    try:
        # Estatísticas gerais
        total_usuarios = Usuario.query.count()
        total_corridas = Corrida.query.count()
        motoristas_online = Usuario.query.filter_by(tipo='motorista', online=True).count()
        passageiros_online = Usuario.query.filter_by(tipo='passageiro').count()
        faturamento_hoje = db.session.query(db.func.sum(Corrida.valor)).filter(
            Corrida.status == 'finalizada',
            db.func.date(Corrida.created_at) == db.func.date('now')
        ).scalar() or 0
        
        # Média de avaliações
        media_avaliacoes = db.session.query(db.func.avg(Avaliacao.nota)).scalar() or 5.0
        
        # Motoristas online (com detalhes)
        motoristas = Usuario.query.filter_by(tipo='motorista', online=True).all()
        motoristas_lista = []
        for m in motoristas:
            motoristas_lista.append({
                'id': m.id,
                'nome': m.nome,
                'carro': m.carro or 'N/A',
                'placa': m.placa or 'N/A',
                'foto_perfil': m.foto_perfil,
                'telefone': m.telefone or 'N/A',
                'nota_media': 5.0
            })
        
        # Passageiros online (com detalhes)
        passageiros = Usuario.query.filter_by(tipo='passageiro').all()
        passageiros_lista = []
        for p in passageiros:
            passageiros_lista.append({
                'id': p.id,
                'nome': p.nome,
                'email': p.email,
                'telefone': p.telefone or 'N/A',
                'foto_perfil': p.foto_perfil
            })
        
        # Corridas ativas (pendente, aceita, em_andamento)
        corridas_ativas = Corrida.query.filter(
            Corrida.status.in_(['pendente', 'aceita', 'em_andamento'])
        ).order_by(Corrida.created_at.desc()).all()
        
        corridas_ativas_lista = []
        for c in corridas_ativas:
            passageiro = Usuario.query.get(c.passageiro_id)
            motorista = Usuario.query.get(c.motorista_id) if c.motorista_id else None
            corridas_ativas_lista.append({
                'corrida_id': c.id,
                'id': c.id,
                'passageiro_id': c.passageiro_id,
                'motorista_id': c.motorista_id,
                'passageiro_nome': passageiro.nome if passageiro else 'N/A',
                'passageiro_telefone': passageiro.telefone if passageiro else '',
                'motorista_nome': motorista.nome if motorista else 'Aguardando',
                'motorista_telefone': motorista.telefone if motorista else '',
                'carro': motorista.carro if motorista else '',
                'placa': motorista.placa if motorista else '',
                'origem': c.origem,
                'destino': c.destino,
                'valor': c.valor,
                'distancia': c.distancia or '',
                'forma_pagamento': c.forma_pagamento or 'pix',
                'status': c.status,
                'created_at': c.created_at.strftime('%Y-%m-%d %H:%M:%S') if c.created_at else None
            })
        
        # Corridas finalizadas (últimas 20)
        corridas_finalizadas = Corrida.query.filter_by(status='finalizada').order_by(
            Corrida.created_at.desc()
        ).limit(20).all()
        
        corridas_finalizadas_lista = []
        for c in corridas_finalizadas:
            passageiro = Usuario.query.get(c.passageiro_id)
            motorista = Usuario.query.get(c.motorista_id) if c.motorista_id else None
            corridas_finalizadas_lista.append({
                'corrida_id': c.id,
                'id': c.id,
                'passageiro_nome': passageiro.nome if passageiro else 'N/A',
                'motorista_nome': motorista.nome if motorista else 'N/A',
                'origem': c.origem,
                'destino': c.destino,
                'valor': c.valor,
                'forma_pagamento': c.forma_pagamento or 'pix',
                'status': c.status,
                'created_at': c.created_at.strftime('%Y-%m-%d %H:%M:%S') if c.created_at else None
            })
        
        # Últimas transações
        transacoes = Transacao.query.order_by(Transacao.data.desc()).limit(10).all()
        transacoes_lista = []
        for t in transacoes:
            usuario = Usuario.query.get(t.usuario_id)
            transacoes_lista.append({
                'id': t.id,
                'usuario_id': t.usuario_id,
                'usuario_nome': usuario.nome if usuario else 'N/A',
                'tipo': t.tipo,
                'valor': t.valor,
                'descricao': t.descricao,
                'data': t.data.strftime('%d/%m/%Y %H:%M') if t.data else None
            })
        
        # Estatísticas para os cards
        estatisticas = {
            'total_usuarios': total_usuarios,
            'total_corridas': total_corridas,
            'motoristas_online': motoristas_online,
            'passageiros_online': passageiros_online,
            'corridas_ativas': len(corridas_ativas_lista),
            'corridas_finalizadas_hoje': len(corridas_finalizadas_lista),
            'faturamento_hoje': float(faturamento_hoje),
            'media_avaliacoes': round(float(media_avaliacoes), 1)
        }
        
        return jsonify({
            'sucesso': True,
            'estatisticas': estatisticas,
            'motoristas_online': motoristas_online,
            'motoristas_online_lista': motoristas_lista,
            'passageiros_online': passageiros_online,
            'passageiros_online_lista': passageiros_lista,
            'corridas_ativas': corridas_ativas_lista,
            'corridas_finalizadas': corridas_finalizadas_lista,
            'transacoes': transacoes_lista,
            'countMotoristasOnline': motoristas_online,
            'countPassageirosOnline': passageiros_online,
            'countCorridasAtivas': len(corridas_ativas_lista),
            'countCorridasFinalizadas': len(corridas_finalizadas_lista),
            'totalFaturamento': f'R$ {float(faturamento_hoje):.2f}',
            'mediaAvaliacoes': round(float(media_avaliacoes), 1)
        })
        
    except Exception as e:
        print(f"❌ Erro no dashboard: {e}")
        return jsonify({
            'sucesso': False,
            'erro': str(e),
            'motoristas_online': 0,
            'motoristas_online_lista': [],
            'passageiros_online_lista': [],
            'corridas_ativas': [],
            'corridas_finalizadas': [],
            'estatisticas': {
                'motoristas_online': 0,
                'passageiros_online': 0,
                'corridas_ativas': 0,
                'corridas_finalizadas_hoje': 0,
                'faturamento_hoje': 0,
                'media_avaliacoes': 5.0
            }
        }), 500
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
#==========MOTORISTAS OLINE PARA PASSAGEIROS==≠=
@app.route('/motoristas_localizacao', methods=['GET'])
def motoristas_localizacao():
    """Retorna motoristas online com posições para o mapa"""
    try:
        motoristas = Usuario.query.filter_by(tipo='motorista', online=True).all()
        lista = []
        
        # Posições de fallback espalhadas por São Paulo
        fallback_positions = [
            (-23.5505, -46.6333),  # Centro
            (-23.5610, -46.6560),  # Oeste
            (-23.5400, -46.6100),  # Leste
            (-23.5700, -46.6400),  # Sul
            (-23.5300, -46.6200),  # Norte
            (-23.5550, -46.6450),  # Centro-Oeste
            (-23.5450, -46.6250),  # Centro-Leste
            (-23.5600, -46.6150),  # Sudeste
            (-23.5350, -46.6500),  # Noroeste
            (-23.5650, -46.6350),  # Sul-Centro
        ]
        
        for i, m in enumerate(motoristas):
            lat = None
            lng = None
            
            # Tenta buscar localização real
            try:
                ultima_loc = db.session.execute(
                    db.text("""
                        SELECT lat, lng FROM localizacoes 
                        WHERE motorista_id = :mid 
                        ORDER BY updated_at DESC LIMIT 1
                    """),
                    {'mid': m.id}
                ).fetchone()
                
                if ultima_loc and ultima_loc[0] and ultima_loc[1]:
                    lat = ultima_loc[0]
                    lng = ultima_loc[1]
            except Exception as e:
                print(f"⚠️ Erro ao buscar localização do motorista {m.id}: {e}")
            
            # Se não tem localização real, usa fallback
            if lat is None or lng is None:
                pos = fallback_positions[i % len(fallback_positions)]
                lat = pos[0] + (i * 0.002)
                lng = pos[1] + (i * 0.002)
            
            lista.append({
                'id': m.id,
                'nome': m.nome,
                'carro': m.carro or 'Carro',
                'placa': m.placa or '',
                'foto_perfil': m.foto_perfil or '',
                'lat': lat,
                'lng': lng,
                'nota': 5.0
            })
        
        print(f"🗺️ Motoristas no mapa: {len(lista)}")
        return jsonify({
            'motoristas': lista,
            'total': len(lista)
        })
    except Exception as e:
        print(f"❌ Erro motoristas_localizacao: {e}")
        # Retorna array vazio em caso de erro
        return jsonify({'motoristas': [], 'total': 0})
@app.route('/minhas_avaliacoes', methods=['GET'])
@jwt_required()
def minhas_avaliacoes():
    """Retorna avaliações recebidas pelo usuário logado"""
    usuario_id = int(get_jwt_identity())
    
    try:
        avaliacoes = Avaliacao.query.filter_by(avaliado_id=usuario_id).order_by(Avaliacao.created_at.desc()).limit(10).all()
        
        lista = []
        for a in avaliacoes:
            avaliador = Usuario.query.get(a.avaliador_id)
            lista.append({
                'id': a.id,
                'corrida_id': a.corrida_id,
                'nota': a.nota,
                'comentario': a.comentario or '',
                'avaliador_nome': avaliador.nome if avaliador else 'Usuário',
                'created_at': a.created_at.strftime('%d/%m/%Y') if a.created_at else ''
            })
        
        # Calcula média
        media = db.session.query(db.func.avg(Avaliacao.nota)).filter_by(avaliado_id=usuario_id).scalar() or 5.0
        
        return jsonify({
            'avaliacoes': lista,
            'media': round(float(media), 1),
            'total': len(lista)
        })
    except Exception as e:
        return jsonify({'avaliacoes': [], 'media': 5.0, 'total': 0})
# ROTAS BÁSICAS
# ==========================================

@app.route("/")
def home():
    return jsonify({"status": "online", "api": "Rota Brasil"})

@app.route("/teste")
def teste():
    return jsonify({"status": "online", "mensagem": "API Rota Brasil funcionando!"})
@app.route('/perfil/<int:usuario_id>', methods=['GET'])
def perfil_usuario(usuario_id):
    """Retorna estatísticas do perfil do usuário"""
    try:
        usuario = Usuario.query.get(usuario_id)
        if not usuario:
            return jsonify({'erro': 'Usuário não encontrado'}), 404
        
        # Número de corridas realizadas (como passageiro ou motorista)
        if usuario.tipo == 'passageiro':
            corridas_realizadas = Corrida.query.filter_by(passageiro_id=usuario_id).count()
            corridas_finalizadas = Corrida.query.filter_by(passageiro_id=usuario_id, status='finalizada').count()
        else:
            corridas_realizadas = Corrida.query.filter_by(motorista_id=usuario_id).count()
            corridas_finalizadas = Corrida.query.filter_by(motorista_id=usuario_id, status='finalizada').count()
        
        # Média de avaliações recebidas
        media_avaliacoes = db.session.query(db.func.avg(Avaliacao.nota)).filter_by(avaliado_id=usuario_id).scalar() or 5.0
        
        # É novo? (menos de 3 corridas)
        is_novo = corridas_realizadas < 3
        
        return jsonify({
            'id': usuario.id,
            'nome': usuario.nome,
            'tipo': usuario.tipo,
            'foto_perfil': usuario.foto_perfil or '',
            'corridas_realizadas': corridas_realizadas,
            'corridas_finalizadas': corridas_finalizadas,
            'media_avaliacoes': round(float(media_avaliacoes), 1),
            'is_novo': is_novo,
            'carro': usuario.carro or '',
            'placa': usuario.placa or ''
        })
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
  

# ==≠≠==≠=Atualizar configurações (admin)
import base64

# Senha do painel admin (ALTERE AQUI!)
SENHA_PAINEL = "admin123"

@app.route('/admin/login', methods=['POST'])
def admin_login():
    """Verifica a senha do painel admin"""
    dados = request.get_json()
    senha = dados.get('senha', '')
    
    if senha == SENHA_PAINEL:
        # Gera um token simples
        token_str = f"admin:{senha}:{datetime.utcnow().timestamp()}"
        token = base64.b64encode(token_str.encode()).decode()
        return jsonify({'sucesso': True, 'token': token})
    else:
        return jsonify({'sucesso': False, 'erro': 'Senha incorreta'}), 401

@app.route('/admin/verificar', methods=['POST'])
def admin_verificar():
    """Verifica se o token é válido"""
    dados = request.get_json()
    token = dados.get('token', '')
    
    try:
        decoded = base64.b64decode(token).decode()
        if decoded.startswith('admin:'):
            return jsonify({'valido': True})
    except:
        pass
    
    return jsonify({'valido': False}), 401
# ========== CONFIGURAÇÕES ==========

@app.route('/configuracoes', methods=['GET'])
def get_configuracoes():
    """Retorna as configurações atuais"""
    try:
        configs = Configuracao.query.all()
        dados = {}
        for c in configs:
            dados[c.chave] = c.valor
        
        # Valores padrão caso não existam
        defaults = {
            'bandeirada': 5.0,
            'preco_km': 2.5,
            'multiplicador_dinamico': 1.0,
            'dinamico_ativo': 0
        }
        for k, v in defaults.items():
            if k not in dados:
                dados[k] = v
        
        return jsonify(dados)
    except Exception as e:
        # Se a tabela não existir, retorna padrões
        return jsonify({
            'bandeirada': 5.0,
            'preco_km': 2.5,
            'multiplicador_dinamico': 1.0,
            'dinamico_ativo': 0
        })

@app.route('/admin/configuracoes', methods=['POST', 'OPTIONS'])
def admin_configuracoes():
    """Salva as configurações de tarifas"""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'})
    
    dados = request.get_json()
    print(f"📥 Recebido para salvar: {dados}")
    
    try:
        for chave, valor in dados.items():
            config = Configuracao.query.filter_by(chave=chave).first()
            if config:
                config.valor = float(valor)
                print(f"📝 Atualizado: {chave} = {valor}")
            else:
                nova = Configuracao(chave=chave, valor=float(valor), descricao=chave)
                db.session.add(nova)
                print(f"➕ Criado: {chave} = {valor}")
        
        db.session.commit()
        print("✅ Configurações salvas com sucesso!")
        return jsonify({'status': 'ok', 'mensagem': 'Configurações salvas!'})
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erro: {e}")
        return jsonify({'erro': str(e)}), 500    
# ==========================================
# INICIAR
# ==========================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
