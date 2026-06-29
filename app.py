import os
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
import time
import mercadopago
from datetime import datetime
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")

if not MP_ACCESS_TOKEN:
    raise ValueError("MP_ACCESS_TOKEN não encontrado no ambiente.")

sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

app = Flask(__name__)
# ✅ CONFIGURAÇÃO CORRETA DO CORS
CORS(app, origins=["*"], methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "Authorization"])

#CORS(app)

# 📌 CONFIGURAÇÃO PARA POSTGRESQL
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///rotabrasil.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "super-secret-key-rota-brasil")


db = SQLAlchemy(app)
jwt = JWTManager(app)

# 📡 SOCKET.IO COMPATÍVEL COM RENDER E NAVEGADORES
socketio = SocketIO(app, cors_allowed_origins="*", transports=['websocket', 'polling'])


# ==========================================
# MODELOS DO BANCO
# ==========================================
class Usuario(db.Model):
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
    admin = db.Column(db.Boolean,default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'nome': self.nome,
            'email': self.email,
            'telefone': self.telefone,
            'tipo': self.tipo,
            'foto_perfil': self.foto_perfil,
            'carro': self.carro,
            'placa': self.placa,
            'online': self.online
        }


class Corrida(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    passageiro_id = db.Column(db.Integer, nullable=False)
    motorista_id = db.Column(db.Integer, nullable=True)
    origem = db.Column(db.String(255), nullable=False)
    destino = db.Column(db.String(255), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="pendente")


class Avaliacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    corrida_id = db.Column(db.Integer)
    avaliador_id = db.Column(db.Integer)
    avaliado_id = db.Column(db.Integer)
    nota = db.Column(db.Integer)
    comentario = db.Column(db.String(255))

class Carteira(db.Model):
    __tablename__ = "carteiras"

    id = db.Column(db.Integer, primary_key=True)

    usuario_id = db.Column(
        db.Integer,
        nullable=False,
        unique=True
    )

    saldo = db.Column(
        db.Float,
        default=0.0
    )

    saldo_bloqueado = db.Column(
        db.Float,
        default=0.0
    )

    criado_em = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
class Transacao(db.Model):
    __tablename__ = "transacoes"

    id = db.Column(db.Integer, primary_key=True)

    usuario_id = db.Column(
        db.Integer,
        nullable=False
    )

    tipo = db.Column(
        db.String(50)
    )

    valor = db.Column(
        db.Float
    )

    descricao = db.Column(
        db.String(300)
    )

    data = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )    
# ==========================================
# ROTAS DE AUTENTICAÇÃO
# ==========================================
@app.route("/register", methods=["POST"])
def register():
    dados = request.get_json()
    senha_cripto = generate_password_hash(dados.get("senha"))
    
    novo_usuario = Usuario(
        nome=dados.get("nome"),
        email=dados.get("email"),
        senha=senha_cripto,
        telefone=dados.get("telefone"),
        tipo=dados.get("tipo", "passageiro"),
        foto_perfil=dados.get("foto_perfil"),
        carro=dados.get("carro"),
        placa=dados.get("placa")
    )
    
    db.session.add(novo_usuario)
    db.session.commit()
    #====criar a carteiro do usuario===
    nova_carteira = Carteira(
    usuario_id=novo_usuario.id
    )

    db.session.add(nova_carteira)
    db.session.commit()
    return jsonify({"status": "Conta criada com sucesso!"}), 201
from functools import wraps
from flask_jwt_extended import (
    verify_jwt_in_request,
    get_jwt_identity
)

def admin_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        # Verifica se existe JWT válido
        verify_jwt_in_request()

        usuario_id = get_jwt_identity()

        usuario = Usuario.query.get(usuario_id)

        # Verifica se é admin
        if not usuario or not usuario.admin:
            return jsonify({
                "erro": "Acesso negado"
            }), 403

        return func(*args, **kwargs)

    return wrapper    
#========Consulta de saldo=====
@app.route("/carteira/saldo")
@jwt_required()
def saldo():

    usuario_id = get_jwt_identity()

    carteira = Carteira.query.filter_by(
        usuario_id=usuario_id
    ).first()

    return jsonify({
        "saldo": carteira.saldo,
        "bloqueado": carteira.saldo_bloqueado
    })
#=======acompanha toda transação ====   
@app.route('/transacoes')
def admin_transacoes():

    transacoes = Transacao.query.all()

    return jsonify([
        {
            "id": t.id,
            "usuario_id": t.usuario_id,
            "tipo": t.tipo,
            "valor": t.valor,
            "descricao": t.descricao
        }
        for t in transacoes
    ])    
#=======Historico da carteira=========    
@app.route('/carteira/historico')
@jwt_required()
def historico():

    usuario_id = get_jwt_identity()

    transacoes = Transacao.query.filter_by(
        usuario_id=usuario_id
    ).order_by(
        Transacao.data.desc()
    ).all()

    return jsonify([
        {
            "tipo": t.tipo,
            "valor": t.valor,
            "descricao": t.descricao,
            "data": t.data.strftime("%d/%m/%Y %H:%M")
        }
        for t in transacoes
    ])    
#=========bliquear valor =======    
def bloquear_valor_corrida(
    usuario_id,
    valor
):

    carteira = Carteira.query.filter_by(
        usuario_id=usuario_id
    ).first()

    if carteira.saldo < valor:
        return False

    carteira.saldo -= valor
    carteira.saldo_bloqueado += valor

    db.session.commit()

    return True    
@app.route("/login", methods=["POST"])
def login():
    dados = request.get_json()
    usuario = Usuario.query.filter_by(email=dados.get("email")).first()
    
    if not usuario or not check_password_hash(usuario.senha, dados.get("senha")):
        return jsonify({"erro": "E-mail ou senha incorretos"}), 401
        
    token = create_access_token(identity=str(usuario.id))
    
    dados_user = {
        "id": usuario.id,
        "nome": usuario.nome,
        "email": usuario.email,
        "tipo": usuario.tipo,
        "foto_perfil": usuario.foto_perfil,
        "carro": usuario.carro,
        "placa": usuario.placa
    }
    
    return jsonify({"token": token, "user": dados_user}), 200


# ==========================================
# STATUS MOTORISTA
# ==========================================
@app.route("/ficar_online/<int:id>", methods=["POST"])
def ficar_online(id):
    motorista = Usuario.query.get(id)
    if motorista:
        motorista.online = True
        db.session.commit()
    return jsonify({"status": "Motorista online"}), 200


@app.route("/ficar_offline/<int:id>", methods=["POST"])
def ficar_offline(id):
    motorista = Usuario.query.get(id)
    if motorista:
        motorista.online = False
        db.session.commit()
    return jsonify({"status": "Motorista offline"}), 200


@app.route("/motoristas_online", methods=["GET"])
def motoristas_online():
    motoristas = Usuario.query.filter_by(tipo="motorista", online=True).all()
    lista = []
    for m in motoristas:
        lista.append({
            "id": m.id,
            "nome": m.nome,
            "foto_perfil": m.foto_perfil,
            "carro": m.carro if m.carro else "Carro Particular",
            "placa": m.placa if m.placa else ""
        })
    return jsonify(lista), 200

#=====liberar pagamento=========
def liberar_pagamento(
    passageiro_id,
    motorista_id,
    valor
):

    plataforma = valor * 0.15

    motorista_recebe = valor - plataforma

    carteira_passageiro = Carteira.query.filter_by(
        usuario_id=passageiro_id
    ).first()

    carteira_motorista = Carteira.query.filter_by(
        usuario_id=motorista_id
    ).first()

    carteira_passageiro.saldo_bloqueado -= valor

    carteira_motorista.saldo += motorista_recebe

    db.session.commit()
#= ======devolução de dinheiro ======
def devolver_saldo(
    usuario_id,
    valor
    ):

    carteira = Carteira.query.filter_by(
        usuario_id=usuario_id
    ).first()

    carteira.saldo += valor
    carteira.saldo_bloqueado -= valor

    db.session.commit()
# ==========================================
# CORRIDAS
# ==========================================
@app.route("/nova_corrida", methods=["POST"])
@jwt_required()
def nova_corrida():

    passageiro_id = get_jwt_identity()
    passageiro = Usuario.query.get(passageiro_id)
    dados = request.get_json()

    valor_corrida = float(dados.get("valor"))

    if not bloquear_valor_corrida(
        passageiro_id,
        valor_corrida
    ):
        return jsonify({
            "erro": "Saldo insuficiente"
        }), 400

    nova = Corrida(
        passageiro_id=passageiro_id,
        origem=dados.get("origem"),
        destino=dados.get("destino"),
        valor=float(dados.get("valor")),
        status="pendente"
    )

    db.session.add(nova)
    db.session.commit()

    dados_chamada = {
        "corrida_id": nova.id,
        "passageiro_id": passageiro.id,
        "passageiro_nome": passageiro.nome,
        "foto_perfil": passageiro.foto_perfil,
        "origem": nova.origem,
        "destino": nova.destino,
        "valor": nova.valor,
        "distancia": dados.get("distancia", "Calculando...")
    }

    motoristas = Usuario.query.filter_by(
        tipo="motorista",
        online=True
    ).all()

    for motorista in motoristas:

        socketio.emit(
            "nova_corrida",
            dados_chamada,
            room=f"motorista_{motorista.id}"
        )

    return jsonify({
        "status": "Procurando motoristas",
        "corrida_id": nova.id
    }), 201
@app.route('/aceitar_corrida/<int:id>', methods=['POST'])
@jwt_required()
def aceitar_corrida(id):
    motorista_id = get_jwt_identity()
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
        "foto_perfil": motorista.foto_perfil,
        "carro": motorista.carro,
        "placa": motorista.placa
    }

    socketio.emit("corrida_aceita", dados_socket, room=f"corrida_{id}")
    return jsonify({"sucesso": True, "corrida_id": corrida.id, "status":"aceita"}), 200


@app.route("/cancelar_corrida/<int:id>", methods=["POST"])
@jwt_required()
def cancelar_corrida(id):
    corrida = Corrida.query.get(id)
    
    # 1. Validações básicas
    if not corrida:
        return jsonify({"sucesso": False, "erro": "Corrida não encontrada"}), 404
        
    if corrida.status == "finalizada":
        return jsonify({"sucesso": False, "erro": "Corrida já finalizada"}), 400
        
    if corrida.status == "cancelada":
        return jsonify({"sucesso": False, "erro": "Corrida já estava cancelada"}), 400

    try:
        # 2. Atualiza o status da corrida
        corrida.status = "cancelada"
        
        # 3. Executa a devolução do dinheiro usando os dados da própria corrida
        # (Ajuste 'passageiro_id' e 'valor' de acordo com as colunas do seu modelo Corrida)
        devolver_saldo(corrida.passageiro_id, corrida.valor)
        
        # 4. Salva todas as alterações no banco de dados de uma vez
        db.session.commit()
        
    except Exception as e:
        # Se der qualquer erro na devolução ou no banco, desfaz as alterações
        db.session.rollback()
        return jsonify({"sucesso": False, "erro": f"Erro ao processar cancelamento: {str(e)}"}), 500

    # 5. Avisa os envolvidos via Socket e retorna o sucesso
    socketio.emit("corrida_cancelada", {"corrida_id": id}, room=f"corrida_{id}")
    
    return jsonify({"sucesso": True, "corrida_id": corrida.id}), 200

@app.route('/finalizar_corrida/<corrida_id>', methods=['POST'])
def finalizar_corrida(corrida_id):

    try:
        corrida_id = int(corrida_id)
    except:
        return jsonify({
            "sucesso": False,
            "erro": "ID inválido"
        }), 400

    dados = request.get_json() or {}

    corrida = Corrida.query.get(corrida_id)

    if not corrida:
        return jsonify({
            "sucesso": False,
            "erro": "Corrida não encontrada"
        }), 404

    corrida.status = "finalizada"

    # Libera pagamento
    liberar_pagamento(
        corrida.passageiro_id,
        corrida.motorista_id,
        corrida.valor
    )

    # Registra no histórico
    registro = Transacao(
        usuario_id=corrida.passageiro_id,
        tipo="corrida",
        valor=corrida.valor,
        descricao=f"Corrida concluída #{corrida.id}"
    )

    db.session.add(registro)

    db.session.commit()

    socketio.emit(
        'viagem_finalizada',
        {
            "corrida_id": corrida_id,
            "valor": corrida.valor,
            "motorista_nome": dados.get(
                'motorista_nome',
                "Motorista"
            ),
            "motorista_id": corrida.motorista_id
        },
        room=f"corrida_{corrida_id}"
    )

    return jsonify({
        "sucesso": True,
        "valor": corrida.valor
    })

# ==========================================
# SOCKETIO — SALAS E EVENTOS ALINHADOS
# ==========================================
@socketio.on("connect")
def on_connect():
    print(f"✅ Cliente conectado")


@socketio.on('entrar_na_sala')
def entrar_na_sala(dados):
    cid = dados.get('corrida_id')
    if cid:
        join_room(f"corrida_{cid}")
        print(f"✅ Entrou na sala corrida_{cid}")


@socketio.on('iniciar_viagem')
def repassar_inicio(dados):
    corrida_id = dados.get('corrida_id')
    if corrida_id:
        socketio.emit('viagem_iniciada', {"corrida_id": corrida_id}, room=f"corrida_{corrida_id}")


@app.route("/atualizar_localizacao", methods=["POST"])
@jwt_required()
def atualizar_localizacao():
    motorista_id = get_jwt_identity()
    dados = request.get_json()
    latitude = dados.get("latitude")
    longitude = dados.get("longitude")

    if not latitude or not longitude:
        return jsonify({"erro": "Coordenadas ausentes"}), 400

    dados_gps = {
        "motorista_id": motorista_id,
        "latitude": float(latitude),
        "longitude": float(longitude)
    }
    socketio.emit("atualizacao_localizacao", dados_gps, room=f"corrida_{dados.get('corrida_id')}")
    return jsonify({"status": "Localização atualizada"}), 200


# ==========================================
# AVALIAÇÕES
# ==========================================
@app.route("/avaliar", methods=["POST"])
@jwt_required()
def avaliar():
    user_id = get_jwt_identity()
    dados = request.get_json()

    avaliacao = Avaliacao(
        corrida_id=dados.get("corrida_id"),
        avaliador_id=user_id,
        avaliado_id=dados.get("avaliado_id"),
        nota=dados.get("nota"),
        comentario=dados.get("comentario")
    )
    db.session.add(avaliacao)
    db.session.commit()
    return jsonify({"status":"avaliado"})


@app.route("/admin/avaliacoes")
def admin_avaliacoes():
    avaliacoes = Avaliacao.query.all()
    lista = []
    for a in avaliacoes:
        avaliador = Usuario.query.get(a.avaliador_id)
        avaliado = Usuario.query.get(a.avaliado_id)
        lista.append({
            "id": a.id,
            "corrida_id": a.corrida_id,
            "avaliador": avaliador.nome if avaliador else "Usuário",
            "avaliado": avaliado.nome if avaliado else "Usuário",
            "nota": a.nota,
            "comentario": a.comentario
        })
    return jsonify(lista)


@app.route("/minhas_avaliacoes", methods=["GET"])
@jwt_required()
def minhas_avaliacoes():
    usuario_id = get_jwt_identity()
    avaliacoes = Avaliacao.query.filter_by(avaliado_id=usuario_id).all()
    lista = []
    for a in avaliacoes:
        lista.append({
            "nota": a.nota,
            "comentario": a.comentario
        })
    return jsonify(lista)


# ==========================================
# ADMIN
# ==========================================
# ==========================================
# ENDPOINTS ADMIN - SEM AUTENTICAÇÃO
# ==========================================

@app.route('/admin/dashboard2', methods=['GET'])
def admin_dashboard2():
    """Dashboard com todas as métricas - SEM AUTENTICAÇÃO"""
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

@app.route('/admin/motoristas', methods=['GET'])
def admin_motoristas():
    """Lista todos os motoristas - SEM AUTENTICAÇÃO"""
    try:
        motoristas = Usuario.query.filter_by(tipo='motorista').all()
        return jsonify([{
            'id': m.id,
            'nome': m.nome,
            'email': m.email,
            'carro': m.carro or 'N/A',
            'placa': m.placa or 'N/A',
            'online': m.online,
            'foto_perfil': m.foto_perfil
        } for m in motoristas])
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/passageiros', methods=['GET'])
def admin_passageiros():
    """Lista todos os passageiros - SEM AUTENTICAÇÃO"""
    try:
        passageiros = Usuario.query.filter_by(tipo='passageiro').all()
        return jsonify([{
            'id': p.id,
            'nome': p.nome,
            'email': p.email,
            'telefone': p.telefone or 'N/A',
            'foto_perfil': p.foto_perfil
        } for p in passageiros])
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/corridas', methods=['GET'])
def admin_corridas():
    """Lista todas as corridas com detalhes - SEM AUTENTICAÇÃO"""
    try:
        corridas = Corrida.query.order_by(Corrida.id.desc()).all()
        lista = []
        for c in corridas:
            passageiro = Usuario.query.get(c.passageiro_id)
            motorista = Usuario.query.get(c.motorista_id) if c.motorista_id else None
            lista.append({
                'id': c.id,
                'passageiro_nome': passageiro.nome if passageiro else 'N/A',
                'motorista_nome': motorista.nome if motorista else 'N/A',
                'origem': c.origem,
                'destino': c.destino,
                'valor': c.valor,
                'status': c.status,
                'data_criacao': getattr(c, 'data_criacao', None)
            })
        return jsonify(lista)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/corridas/recentes', methods=['GET'])
def admin_corridas_recentes():
    """Últimas 10 corridas - SEM AUTENTICAÇÃO"""
    try:
        corridas = Corrida.query.order_by(Corrida.id.desc()).limit(10).all()
        lista = []
        for c in corridas:
            passageiro = Usuario.query.get(c.passageiro_id)
            motorista = Usuario.query.get(c.motorista_id) if c.motorista_id else None
            lista.append({
                'id': c.id,
                'passageiro_nome': passageiro.nome if passageiro else 'N/A',
                'motorista_nome': motorista.nome if motorista else 'N/A',
                'valor': c.valor,
                'status': c.status,
                'data_criacao': getattr(c, 'data_criacao', None)
            })
        return jsonify(lista)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/avaliacoes', methods=['GET'])
def admin_avaliacoes():
    """Lista todas as avaliações - SEM AUTENTICAÇÃO"""
    try:
        avaliacoes = Avaliacao.query.all()
        lista = []
        for a in avaliacoes:
            avaliador = Usuario.query.get(a.avaliador_id)
            avaliado = Usuario.query.get(a.avaliado_id)
            lista.append({
                'id': a.id,
                'corrida_id': a.corrida_id,
                'avaliador': avaliador.nome if avaliador else 'N/A',
                'avaliado': avaliado.nome if avaliado else 'N/A',
                'nota': a.nota,
                'comentario': a.comentario
            })
        return jsonify(lista)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/transacoes', methods=['GET'])
def admin_transacoes():
    """Lista todas as transações - SEM AUTENTICAÇÃO"""
    try:
        transacoes = Transacao.query.order_by(Transacao.id.desc()).all()
        return jsonify([{
            'id': t.id,
            'usuario_id': t.usuario_id,
            'tipo': t.tipo,
            'valor': t.valor,
            'descricao': t.descricao,
            'data': t.data.strftime('%d/%m/%Y %H:%M') if hasattr(t, 'data') else None
        } for t in transacoes])
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/excluir_motorista/<int:id>', methods=['DELETE'])
def admin_excluir_motorista(id):
    """Exclui motorista e todos os dados relacionados - SEM AUTENTICAÇÃO"""
    try:
        motorista = Usuario.query.get(id)
        if not motorista:
            return jsonify({'erro': 'Motorista não encontrado'}), 404
        
        # Excluir carteira
        Carteira.query.filter_by(usuario_id=id).delete()
        
        # Excluir transações
        Transacao.query.filter_by(usuario_id=id).delete()
        
        # Excluir avaliações relacionadas
        Avaliacao.query.filter((Avaliacao.avaliador_id == id) | (Avaliacao.avaliado_id == id)).delete()
        
        db.session.delete(motorista)
        db.session.commit()
        
        return jsonify({'status': 'Motorista excluído com sucesso'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/excluir_passageiro/<int:id>', methods=['DELETE'])
def admin_excluir_passageiro(id):
    """Exclui passageiro e todos os dados relacionados - SEM AUTENTICAÇÃO"""
    try:
        passageiro = Usuario.query.get(id)
        if not passageiro:
            return jsonify({'erro': 'Passageiro não encontrado'}), 404
        
        # Excluir carteira
        Carteira.query.filter_by(usuario_id=id).delete()
        
        # Excluir transações
        Transacao.query.filter_by(usuario_id=id).delete()
        
        # Excluir avaliações relacionadas
        Avaliacao.query.filter((Avaliacao.avaliador_id == id) | (Avaliacao.avaliado_id == id)).delete()
        
        db.session.delete(passageiro)
        db.session.commit()
        
        return jsonify({'status': 'Passageiro excluído com sucesso'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/adicionar_saldo/<int:id>', methods=['POST'])
def admin_adicionar_saldo(id):
    """Adiciona saldo a qualquer usuário - SEM AUTENTICAÇÃO"""
    try:
        dados = request.get_json()
        valor = float(dados.get('valor', 0))
        
        if valor <= 0:
            return jsonify({'erro': 'Valor deve ser maior que zero'}), 400
        
        # Verifica se o usuário existe
        usuario = Usuario.query.get(id)
        if not usuario:
            return jsonify({'erro': 'Usuário não encontrado'}), 404
        
        # Busca ou cria carteira
        carteira = Carteira.query.filter_by(usuario_id=id).first()
        if not carteira:
            carteira = Carteira(usuario_id=id, saldo=0, saldo_bloqueado=0)
            db.session.add(carteira)
        
        # Adiciona saldo
        carteira.saldo += valor
        
        # Registra transação
        transacao = Transacao(
            usuario_id=id,
            tipo='credito',
            valor=valor,
            descricao=f'Adicionado pelo admin: R$ {valor:.2f}',
            data=datetime.utcnow()
        )
        db.session.add(transacao)
        
        db.session.commit()
        
        return jsonify({
            'status': 'Saldo adicionado com sucesso',
            'novo_saldo': carteira.saldo
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/usuarios', methods=['GET'])
def admin_usuarios():
    """Lista todos os usuários - SEM AUTENTICAÇÃO"""
    try:
        usuarios = Usuario.query.all()
        return jsonify([u.to_dict() for u in usuarios])
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/admin/carteiras', methods=['GET'])
def admin_carteiras():
    """Lista todas as carteiras - SEM AUTENTICAÇÃO"""
    try:
        carteiras = Carteira.query.all()
        return jsonify([{
            'id': c.id,
            'usuario_id': c.usuario_id,
            'saldo': c.saldo,
            'saldo_bloqueado': c.saldo_bloqueado,
            'criado_em': c.criado_em.strftime('%Y-%m-%d %H:%M') if c.criado_em else None
        } for c in carteiras])
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

# ==========================================
# DEMAIS ROTAS
# ==========================================
@app.route("/atualizar_foto", methods=["POST"])
@jwt_required()
def atualizar_foto():
    usuario_id = get_jwt_identity()
    usuario = Usuario.query.get(usuario_id)
    if not usuario:
        return jsonify({"erro": "Usuário não encontrado"}), 404
    dados = request.get_json()
    usuario.foto_perfil = dados.get("foto_perfil")
    db.session.commit()
    return jsonify({"status": "Foto atualizada com sucesso", "foto_perfil": usuario.foto_perfil}), 200


@app.route("/teste")
def teste():
    return jsonify({"status": "online", "mensagem": "API Rota Brasil funcionando!"}), 200


@app.route("/recriar")
def recriar():
    with app.app_context():
        db.drop_all()
        db.create_all()
    return "Banco recriado"


# 📄 ROTAS DE TELAS
@app.route("/")
def index(): return render_template("index.html")
@app.route("/passageiro")
def passageiro(): return render_template("passageiro.html")
@app.route("/motorista")
def motorista(): return render_template("motorista.html")
@app.route("/cadastro")
def cadastro(): return render_template("cadastro.html")
@app.route('/teste/adicionar_saldo/<int:usuario_id>')
def adicionar_saldo(usuario_id):

    carteira = Carteira.query.filter_by(
        usuario_id=usuario_id
    ).first()

    carteira.saldo += 100

    db.session.commit()

    return jsonify({
        "saldo": carteira.saldo
    })
    
@app.route('/criar_adms')
def criar_adms():

    adm1 = Usuario.query.filter_by(
        email="rotabrasil@junior.com"
    ).first()

    adm2 = Usuario.query.filter_by(
        email="rotabrasil@ferreira.com"
    ).first()

    if adm1:
        adm1.admin = True

    if adm2:
        adm2.admin = True

    db.session.commit()

    return jsonify({
        "sucesso": True
    })
    
#=======≠=PAINEL DE CONTROLE ROTA BRASIL========

@app.route('/admin')
def admin():
    return render_template('admin.html')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard3():

    usuarios = Usuario.query.count()

    corridas = Corrida.query.count()

    motoristas_online = Usuario.query.filter_by(
        online=True
    ).count()

    saldo_total = db.session.query(
        db.func.sum(Carteira.saldo)
    ).scalar() or 0

    return jsonify({
        "usuarios": usuarios,
        "corridas": corridas,
        "motoristas_online": motoristas_online,
        "saldo_total": saldo_total
    })


@socketio.on("motorista_online")
def motorista_online(dados):

    motorista_id = dados["id"]

    join_room(
        f"motorista_{motorista_id}"
    )

    print(
        f"Motorista {motorista_id} entrou na sala"
    )
#@app.route("/pix/criar", methods=["POST"])
#@jwt_required()
def criar_pix():

    usuario_id = get_jwt_identity()

    dados = request.get_json()

    valor = float(
        dados.get("valor", 0)
    )

    pagamento = sdk.payment().create({
        "transaction_amount": valor,
        "description": "Recarga carteira Rota Brasil",
        "payment_method_id": "pix",
        "payer": {
            "email": "cliente@rotabrasil.com"
        }
    })

    return jsonify(
        pagamento["response"]
    )    

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    print("WEBHOOK RECEBIDO:", data)

    payment_id = data.get("data", {}).get("id")

    if payment_id:
        payment_info = sdk.payment().get(payment_id)
        status = payment_info["response"]["status"]

        print("STATUS:", status)

    return "OK", 200
@app.route("/checkout/criar", methods=["POST"])
@jwt_required()
def criar_checkout():

    dados = request.get_json()
    valor = float(dados["valor"])

    preference_data = {
        "items": [
            {
                "title": "Recarga Carteira",
                "quantity": 1,
                "unit_price": valor
            }
        ]
    }

    preference = sdk.preference().create(preference_data)

    response = preference.get("response", {})

    link = response.get("init_point") or response.get("sandbox_init_point")

    return jsonify({"link": link}) 
#π√%✓∆ Caucular corrida openRout $€÷=====
#================={{{{{{{{{=====≠=========

import math






BANDEIRADA = 5.0
VALOR_KM = 2.5

# 🔑 COLOQUE SUA CHAVE AQUI
ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjBkNzdmNzYyMzU3YzQxZThhODJjMDNlMmJlOTJlMTNiIiwiaCI6Im11cm11cjY0In0="

@app.route("/calcular_corrida", methods=["POST", "OPTIONS"])
def calcular_corrida():
    # ✅ Responde a requisições OPTIONS (preflight)
    if request.method == "OPTIONS":
        response = jsonify({"status": "ok"})
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization")
        return response
    
    try:
        # ✅ Verifica se os dados foram recebidos
        if not request.json:
            return jsonify({"erro": "Dados não recebidos"}), 400
            
        dados = request.get_json()
        print(f"📥 Dados recebidos: {dados}")
        
        # ✅ Verifica se as coordenadas existem
        if not dados.get("lat_origem") or not dados.get("lon_origem") or not dados.get("lat_destino") or not dados.get("lon_destino"):
            return jsonify({"erro": "Coordenadas incompletas"}), 400
        
        lat_origem = float(dados["lat_origem"])
        lon_origem = float(dados["lon_origem"])
        lat_destino = float(dados["lat_destino"])
        lon_destino = float(dados["lon_destino"])
        
        # TENTA PRIMEIRO: OpenRouteService
        try:
            url = "https://api.openrouteservice.org/v2/directions/driving-car"
            headers = {
                "Authorization": ORS_API_KEY,
                "Content-Type": "application/json"
            }
            body = {
                "coordinates": [
                    [lon_origem, lat_origem],
                    [lon_destino, lat_destino]
                ]
            }
            
            print(f"📤 Enviando para ORS: {body}")
            response = requests.post(url, json=body, headers=headers, timeout=10)
            print(f"📊 Status ORS: {response.status_code}")
            
            if response.status_code == 200:
                dados_rota = response.json()
                if dados_rota.get("routes") and len(dados_rota["routes"]) > 0:
                    distancia_metros = dados_rota["routes"][0]["summary"]["distance"]
                    distancia_km = distancia_metros / 1000
                    tempo_segundos = dados_rota["routes"][0]["summary"]["duration"]
                    tempo_minutos = tempo_segundos / 60
                    
                    valor = BANDEIRADA + (distancia_km * VALOR_KM)
                    
                    resultado = {
                        "distancia": round(distancia_km, 2),
                        "valor": round(valor, 2),
                        "tempo": round(tempo_minutos, 0),
                        "fonte": "ORS"
                    }
                    
                    print(f"✅ Resposta: {resultado}")
                    return jsonify(resultado)
        except Exception as e:
            print(f"⚠️ Erro no ORS: {e}")
        
        # SEGUNDA TENTATIVA: OSRM (gratuito, sem chave)
        try:
            url = f"http://router.project-osrm.org/route/v1/driving/{lon_origem},{lat_origem};{lon_destino},{lat_destino}?overview=false"
            print(f"📤 Tentando OSRM: {url}")
            
            response = requests.get(url, timeout=10)
            print(f"📊 Status OSRM: {response.status_code}")
            
            if response.status_code == 200:
                dados_rota = response.json()
                if dados_rota.get("routes") and len(dados_rota["routes"]) > 0:
                    distancia_metros = dados_rota["routes"][0]["distance"]
                    distancia_km = distancia_metros / 1000
                    tempo_segundos = dados_rota["routes"][0]["duration"]
                    tempo_minutos = tempo_segundos / 60
                    
                    valor = BANDEIRADA + (distancia_km * VALOR_KM)
                    
                    resultado = {
                        "distancia": round(distancia_km, 2),
                        "valor": round(valor, 2),
                        "tempo": round(tempo_minutos, 0),
                        "fonte": "OSRM"
                    }
                    
                    print(f"✅ Resposta: {resultado}")
                    return jsonify(resultado)
        except Exception as e:
            print(f"⚠️ Erro no OSRM: {e}")
        
        # ÚLTIMO RECURSO: Calcular distância aproximada
        print("🔄 Usando cálculo aproximado (Haversine)")
        
        R = 6371
        lat1 = math.radians(lat_origem)
        lon1 = math.radians(lon_origem)
        lat2 = math.radians(lat_destino)
        lon2 = math.radians(lon_destino)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        distancia_km = R * c
        
        tempo_minutos = (distancia_km / 30) * 60
        valor = BANDEIRADA + (distancia_km * VALOR_KM)
        
        resultado = {
            "distancia": round(distancia_km, 2),
            "valor": round(valor, 2),
            "tempo": round(tempo_minutos, 0),
            "fonte": "Haversine (aproximado)"
        }
        
        print(f"✅ Resposta: {resultado}")
        return jsonify(resultado)
        
    except Exception as e:
        print(f"❌ ERRO: {e}")
        return jsonify({"erro": str(e)}), 500

@app.route("/teste2", methods=["GET"])
def teste2():
    return jsonify({
        "status": "online",
        "mensagem": "API de cálculo de corrida funcionando! 🚗"
    })

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "endpoints": [
            "GET  /teste",
            "GET  /",
            "POST /calcular_corrida"
        ]
    })



    
# ==========================================
# INICIAR
# ==========================================
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
