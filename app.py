import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_socketio import SocketIO
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
CORS(app)

# CONFIGURAÇÃO INTELIGENTE PARA POSTGRESQL
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///rotabrasil.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "super-secret-key-rota-brasil")


db = SQLAlchemy(app)
jwt = JWTManager(app)

# 🔧 CORREÇÃO CRUCIAL PARA O RENDER SOCKET.IO
socketio = SocketIO(app, cors_allowed_origins="*", transports=['websocket', 'polling'])

# ==========================================
# MODELOS DO BANCO DE DADOS (CORRIGIDO ✅)
# REMOVI O CAMPO DISTANCIA DAQUI DE BAIXO!
# ==========================================

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)
    telefone = db.Column(db.String(20))
    tipo = db.Column(db.String(20), default="passageiro")
    carro = db.Column(db.String(50), nullable=True)
    placa = db.Column(db.String(20), nullable=True)
    online = db.Column(db.Boolean, default=False)

class Corrida(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    passageiro_id = db.Column(db.Integer, nullable=False)
    motorista_id = db.Column(db.Integer, nullable=True)
    origem = db.Column(db.String(255), nullable=False)
    destino = db.Column(db.String(255), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    # 🚨 REMOVI A LINHA "distancia = ..." DAQUI! AGORA NÃO EXISTE MAIS NO BANCO
    status = db.Column(db.String(20), default="pendente")
#===========SISTEMA DE AVALIACAO=======
class Avaliacao(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    corrida_id = db.Column(
        db.Integer
    )

    avaliador_id = db.Column(
        db.Integer
    )

    avaliado_id = db.Column(
        db.Integer
    )

    nota = db.Column(
        db.Integer
    )

    comentario = db.Column(
        db.String(255)
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
        carro=dados.get("carro"),
        placa=dados.get("placa")
    )
    
    db.session.add(novo_usuario)
    db.session.commit()
    return jsonify({"status": "Conta criada com sucesso!"}), 201

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
        "carro": usuario.carro,
        "placa": usuario.placa
    }
    
    return jsonify({"token": token, "user": dados_user}), 200
# =========================
# 🔴 MOTORISTA OFFLINE
# =========================
@app.route("/ficar_offline/<int:id>", methods=["POST"])
def ficar_offline(id):

    motorista = Usuario.query.get(id)

    if motorista:
        motorista.online = False
        db.session.commit()

    return jsonify({"status": "Motorista offline"}), 200

# ==========================================
# ROTAS DO MOTORISTA
# ==========================================
@app.route("/ficar_online/<int:id>", methods=["POST"])
def ficar_online(id):
    motorista = Usuario.query.get(id)
    if motorista:
        motorista.online = True
        db.session.commit()
    return jsonify({"status": "Motorista online"}), 200

@app.route("/motoristas_online", methods=["GET"])
def motoristas_online():
    motoristas = Usuario.query.filter_by(tipo="motorista", online=True).all()
    lista = []
    for m in motoristas:
        lista.append({
            "id": m.id,
            "nome": m.nome,
            "carro": m.carro if m.carro else "Carro Particular",
            "placa": m.placa if m.placa else ""
        })
    return jsonify(lista), 200

@app.route('/aceitar_corrida/<int:id>', methods=['POST'])
@jwt_required()
def aceitar_corrida(id):
    motorista_id = get_jwt_identity()
    motorista = Usuario.query.get(motorista_id)
    corrida = Corrida.query.get(id)
    
    if not corrida:
        return jsonify({"erro": "Corrida não encontrada"}), 404
        
    if corrida.status != "pendente":
        return jsonify({"erro": "Esta corrida já foi aceita por outro motorista"}), 400

    corrida.motorista_id = motorista.id
    corrida.status = "aceita"
    db.session.commit()

    dados_socket = {
        "corrida_id": corrida.id,
        "motorista_id": motorista.id,
        "motorista_nome": motorista.nome,
        "carro": motorista.carro if motorista.carro else "Carro Particular",
        "placa": motorista.placa if motorista.placa else "Sem Placa"
    }

    socketio.emit("corrida_aceita", dados_socket)
    socketio.emit("corrida_removida", {"corrida_id": corrida.id})

    return jsonify({"status": "Corrida aceita com sucesso", "corrida_id": corrida.id}), 200

# ==========================================
# ROTAS DO PASSAGEIRO (CORRIGIDA ✅ SEM DISTANCIA NO INSERT)
# ==========================================
@app.route("/nova_corrida", methods=["POST"])
@jwt_required()
def nova_corrida():
    passageiro_id = get_jwt_identity()
    passageiro = Usuario.query.get(passageiro_id)
    dados = request.get_json()
    
    # 🔧 AQUI É O PRINCIPAL: REMOVI A LINHA DE "distancia" DA CRIAÇÃO DA CORRIDA
    nova = Corrida(
        passageiro_id=passageiro_id,
        origem=dados.get("origem"),
        destino=dados.get("destino"),
        valor=float(dados.get("valor")),
        status="pendente"
    )
    
    db.session.add(nova)
    db.session.commit()
    
    # ✅ AQUI EU ENVIO A DISTANCIA APENAS PARA TELA, NÃO SALVO NO BANCO!
    dados_chamada = {
        "corrida_id": nova.id,
        "passageiro_id": passageiro.id,
        "passageiro_nome": passageiro.nome,
        "origem": nova.origem,
        "destino": nova.destino,
        "valor": nova.valor,
        "distancia": dados.get("distancia", "Calculando...") # <-- Vem do frontend, só mostra
    }
    
    socketio.emit("nova_corrida", dados_chamada)
    return jsonify({"status": "Procurando motoristas", "corrida_id": nova.id}), 201

@app.route("/cancelar_corrida/<int:id>", methods=["POST"])
@jwt_required()
def cancelar_corrida(id):
    corrida = Corrida.query.get(id)
    if not corrida:
        return jsonify({"erro": "Corrida não encontrada"}), 404

    corrida.status = "cancelada"
    db.session.commit()

    socketio.emit("corrida_cancelada", {"corrida_id": corrida.id})
    return jsonify({"status": "cancelada"}), 200

# ==========================================
# ROTAS DE MONITORAMENTO GPS
# ==========================================
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
    
    socketio.emit("localizacao_motorista", dados_gps)
    return jsonify({"status": "Localização atualizada"}), 200

# EVENTO PADRÃO DO SOCKETIO
@socketio.on("connect")
def on_connect():
    print(f"✅ Cliente conectado com sucesso!")
# =========================================
# LISTAR MOTORISTAS
# =========================================

#@app.route("/admin/motoristas")
#def admin_motoristas():

   # motoristas = Motorista.query.all()

   # lista = []

    #for m in motoristas:

       # user = User.query.get(m.user_id)

       # lista.append({

            #"id": m.id,

            #"user_id": m.user_id,

           # "nome": user.nome if user else "Motorista",

           # "email": user.email if user else "",

           # "carro": m.carro,

           # "placa": m.placa,

            #"online": m.online

       # })

   # return jsonify(lista)


# =========================================
# Rota para recriar bd /perigosa
# =========================================
@app.route("/recriar")
def recriar():

    db.drop_all()

    db.create_all()

    return "banco recriado"
# =========================================

# =========================================


# =========================================

# =========================================
# LISTAR MOTORISTAS ADM
# =========================================

@app.route("/admin/motoristas")
def admin_motoristas():

    motoristas = Usuario.query.filter_by(
        tipo="motorista"
    ).all()

    lista = []

    for m in motoristas:

        lista.append({

            "id": m.id,

            "nome": m.nome,

            "email": m.email,

            "carro": m.carro if m.carro else "Carro Particular",

            "placa": m.placa if m.placa else "",

            "online": m.online

        })

    return jsonify(lista), 200


# =========================================
# EXCLUIR MOTORISTA ADM
# =========================================

@app.route(
    "/admin/excluir_motorista/<int:id>",
    methods=["DELETE"]
)
def excluir_motorista(id):

    motorista = Usuario.query.get(id)

    if not motorista:

        return jsonify({
            "erro":"motorista nao encontrado"
        }), 404

    db.session.delete(motorista)

    db.session.commit()

    return jsonify({
        "status":"motorista excluido"
    }), 200
# =========================================
# LISTAR PASSAGEIROS ADM
# =========================================

@app.route("/admin/passageiros")
def admin_passageiros():

    passageiros = Usuario.query.filter_by(
        tipo="passageiro"
    ).all()

    lista = []

    for p in passageiros:

        lista.append({

            "id": p.id,

            "nome": p.nome,

            "email": p.email,

            "telefone": p.telefone if p.telefone else ""

        })

    return jsonify(lista), 200


# =========================================
# EXCLUIR PASSAGEIRO ADM
# =========================================

@app.route(
    "/admin/excluir_passageiro/<int:id>",
    methods=["DELETE"]
)
def excluir_passageiro(id):

    passageiro = Usuario.query.get(id)

    if not passageiro:

        return jsonify({
            "erro":"passageiro nao encontrado"
        }), 404

    db.session.delete(passageiro)

    db.session.commit()

    return jsonify({
        "status":"passageiro excluido"
    }), 200    
#========≠ROTA DE AVALIAÇÃO======
@app.route(
    "/avaliar",
    methods=["POST"]
)
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

    return jsonify({
        "status":"avaliado"
    })
  
#======== Avaliações no painel ADM ========

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
#=======≠===Minhas Avaliações ==========     
@app.route("/minhas_avaliacoes", methods=["GET"])
@jwt_required()
def minhas_avaliacoes():

    usuario_id = get_jwt_identity()

    conn = conectar()
    c = conn.cursor(dictionary=True)

    c.execute("""
        SELECT nota, comentario, created_at
        FROM avaliacoes
        WHERE avaliado_id = %s
        ORDER BY id DESC
    """, (usuario_id,))

    avaliacoes = c.fetchall()

    conn.close()

    return jsonify(avaliacoes)
 
@app.route("/finalizar_corrida/<int:corrida_id>", methods=["POST"])
@jwt_required()
def finalizar_corrida(corrida_id):

    corrida = Corrida.query.get(corrida_id)

    if not corrida:
        return jsonify({"erro":"Corrida não encontrada"}),404

    corrida.status = "finalizada"

    db.session.commit()

    return jsonify({
        "sucesso": True,
        "mensagem": "Corrida finalizada"
    })
 # 🔄 REPASSA FINALIZAÇÃO MOTORISTA ➡️ PASSAGEIRO
@socketio.on('corrida_finalizada')
def repassar_finalizacao(dados):
    corrida_id = dados.get('corrida_id')
    valor = dados.get('valor')
    motorista_nome = dados.get('motorista_nome')

    if not corrida_id or valor is None:
        return

    # 📡 ENVIA PARA O PASSAGEIRO NO EVENTO CERTO
    emit('viagem_finalizada', {
        "corrida_id": corrida_id,
        "valor": valor,
        "motorista_nome": motorista_nome
    }, room=f"corrida_{corrida_id}")
@socketio.on('entrar_na_sala')
def entrar_na_sala(dados):
    cid = dados.get('corrida_id')
    if cid:
        join_room(f"corrida_{cid}") # <- Adiciona o usuário na sala
        print(f"👤 Usuário entrou na sala corrida_{cid}")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    
    port = int(os.environ.get("PORT", 5000))
    # 🔧 MODO DEBUG DESLIGADO PARA PRODUÇÃO NO RENDER (MAIS ESTÁVEL)
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
