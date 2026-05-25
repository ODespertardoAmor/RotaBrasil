import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_socketio import SocketIO
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)
# Importando ferramentas para segurança de senhas
from werkzeug.security import generate_password_hash, check_password_hash

# =========================================
# APP CONFIGURAÇÃO
# =========================================

app = Flask(__name__)
CORS(app)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "segredo-super-secreto")
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "jwt-segredo-super-secreto")

# Configuração e correção da URL do PostgreSQL
database_url = os.environ.get("DATABASE_URL", "sqlite:///transporte.db") # Fallback para SQLite local
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
jwt = JWTManager(app)

# SocketIO configurado para rodar de forma assíncrona estável
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# =========================================
# MODELOS (BANCO DE DADOS)
# =========================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha = db.Column(db.Text, nullable=False) # Armazenará o hash criptografado
    telefone = db.Column(db.String(20))
    tipo = db.Column(db.String(20), default="passageiro") # passageiro ou motorista

    # Relacionamento para facilitar a busca do perfil de motorista se houver
    motorista_perfil = db.relationship('Motorista', backref='user', uselist=False)


class Motorista(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    carro = db.Column(db.String(120), default="Veículo")
    placa = db.Column(db.String(20), default="ABC-0000")
    foto = db.Column(db.String(500), default="https://i.imgur.com/6VBx3io.png")
    online = db.Column(db.Boolean, default=False)


class Corrida(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    passageiro_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    motorista_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    origem = db.Column(db.String(255), nullable=False)
    destino = db.Column(db.String(255), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default="pendente") # pendente, aceita, cancelada, finalizada


# =========================================
# INICIALIZAÇÃO AUTOMÁTICA DO BANCO
# =========================================

with app.app_context():
    db.create_all()

# =========================================
# ROTAS DE AUTENTICAÇÃO
# =========================================

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    nome = data.get("nome")
    email = data.get("email")
    senha = data.get("senha")
    telefone = data.get("telefone")
    tipo = data.get("tipo", "passageiro")

    if not nome or not email or not senha:
        return jsonify({"erro": "Campos obrigatórios faltando"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"erro": "E-mail já cadastrado"}), 400

    # Criptografando a senha antes de salvar
    senha_criptografada = generate_password_hash(senha)

    user = User(
        nome=nome,
        email=email,
        senha=senha_criptografada,
        telefone=telefone,
        tipo=tipo
    )
    db.session.add(user)
    db.session.commit()

    return jsonify({"status": "criado", "user_id": user.id}), 201


@app.route("/registrar_motorista", methods=["POST"])
def registrar_motorista():
    data = request.get_json()
    nome = data.get("nome")
    email = data.get("email")
    senha = data.get("senha")
    carro = data.get("carro", "Veículo")
    placa = data.get("placa", "ABC-0000")
    foto = data.get("foto", "https://i.imgur.com/6VBx3io.png")

    if not nome or not email or not senha:
        return jsonify({"erro": "Campos obrigatórios faltando"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"erro": "E-mail já cadastrado"}), 400

    senha_criptografada = generate_password_hash(senha)

    user = User(
        nome=nome,
        email=email,
        senha=senha_criptografada,
        tipo="motorista"
    )
    db.session.add(user)
    db.session.commit()

    motorista = Motorista(
        user_id=user.id,
        carro=carro,
        placa=placa,
        foto=foto,
        online=False
    )
    db.session.add(motorista)
    db.session.commit()

    return jsonify({"status": "motorista criado", "user_id": user.id}), 201


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    senha = data.get("senha")

    user = User.query.filter_by(email=email).first()

    # Verificando se o usuário existe E se a senha descriptografada bate
    if not user or not check_password_hash(user.senha, senha):
        return jsonify({"erro": "Login ou senha inválidos"}), 401

    token = create_access_token(identity=str(user.id))

    return jsonify({
        "token": token,
        "user": {
            "id": user.id,
            "nome": user.nome,
            "tipo": user.tipo
        }
    })

# =========================================
# CONTROLE DE FLUXO DOS MOTORISTAS
# =========================================

@app.route("/motoristas_online", methods=["GET"])
def motoristas_online():
    motoristas = Motorista.query.filter_by(online=True).all()
    lista = []
    for m in motoristas:
        lista.append({
            "id": m.id,
            "user_id": m.user_id,
            "nome": m.user.nome,
            "carro": m.carro,
            "placa": m.placa,
            "foto": m.foto
        })
    return jsonify(lista)


@app.route("/ficar_online/<int:user_id>", methods=["POST"])
def ficar_online(user_id):
    m = Motorista.query.filter_by(user_id=user_id).first()
    if not m:
        m = Motorista(user_id=user_id)
    
    m.online = True
    db.session.add(m)
    db.session.commit()
    return jsonify({"status": "online"})


@app.route("/ficar_offline/<int:user_id>", methods=["POST"])
def ficar_offline(user_id):
    motorista = Motorista.query.filter_by(user_id=user_id).first()
    if motorista:
        motorista.online = False
        db.session.commit()
    return jsonify({"status": "offline"})

# =========================================
# CORE DAS CORRIDAS (REAL-TIME E SEGURANÇA)
# =========================================

@app.route("/nova_corrida", methods=["POST"])
@jwt_required()
def nova_corrida():
    data = request.get_json()
    passageiro_id = get_jwt_identity()

    corrida = Corrida(
        passageiro_id=int(passageiro_id),
        origem=data["origem"],
        destino=data["destino"],
        valor=float(data["valor"]),
        status="pendente"
    )
    db.session.add(corrida)
    db.session.commit()

    passageiro = User.query.get(corrida.passageiro_id)

    # Emite via WebSocket para TODOS os motoristas conectados que há uma nova corrida
    socketio.emit(
        "nova_corrida",
        {
            "corrida_id": corrida.id,
            "origem": corrida.origem,
            "destino": corrida.destino,
            "valor": corrida.valor,
            "passageiro_nome": passageiro.nome
        }
    )

    return jsonify({"status": "ok", "corrida_id": corrida.id}), 201


@app.route("/aceitar_corrida/<int:id>", methods=["POST"])
@jwt_required()
def aceitar_corrida(id):
    try:
        user_id = int(get_jwt_identity())
        corrida = Corrida.query.get(id)

        if not corrida:
            return jsonify({"erro": "Corrida não encontrada"}), 404

        # TRAVA DE CONCORRÊNCIA: Se a corrida não estiver mais pendente, outro já aceitou!
        if corrida.status != "pendente":
            return jsonify({"erro": "Esta corrida já foi aceita por outro motorista!"}), 400

        # Atualiza a corrida com o motorista que clicou primeiro
        corrida.motorista_id = user_id
        corrida.status = "aceita"
        db.session.commit()

        # Remove a corrida da tela dos outros motoristas
        socketio.emit("corrida_removida", {"corrida_id": corrida.id}, broadcast=True)

        motorista_user = User.query.get(user_id)
        motorista = Motorista.query.filter_by(user_id=user_id).first()

        # Avisa especificamente o passageiro que a corrida foi aceita
        socketio.emit(
            "corrida_aceita",
            {
                "corrida_id": corrida.id,
                "motorista_id": user_id,
                "motorista_nome": motorista_user.nome if motorista_user else "Motorista",
                "placa": motorista.placa if motorista else "ABC-0000",
                "carro": motorista.carro if motorista else "Veículo",
                "origem": corrida.origem,
                "destino": corrida.destino,
                "foto": motorista.foto if motorista else "https://i.imgur.com/6VBx3io.png"
            },
            broadcast=True # Em produção, idealmente você enviará para a "sala/room" do passageiro
        )

        return jsonify({
            "status": "ok",
            "origem": corrida.origem,
            "destino": corrida.destino,
            "corrida_id": corrida.id
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 500


@app.route("/cancelar_corrida/<int:id>", methods=["POST"])
@jwt_required()
def cancelar_corrida(id):
    corrida = Corrida.query.get(id)
    if not corrida:
        return jsonify({"erro": "Corrida não encontrada"}), 404

    corrida.status = "cancelada"
    db.session.commit()

    socketio.emit("corrida_cancelada", {"corrida_id": corrida.id}, broadcast=True)
    return jsonify({"status": "cancelada"})


@app.route("/atualizar_localizacao", methods=["POST"])
@jwt_required()
def atualizar_localizacao():
    data = request.get_json()
    motorista_id = get_jwt_identity()
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    # Envia a posição do motorista em tempo real para o mapa do passageiro
    socketio.emit(
        "localizacao_motorista",
        {
            "motorista_id": int(motorista_id),
            "latitude": latitude,
            "longitude": longitude
        },
        broadcast=True
    )
    return jsonify({"status": "localizacao atualizada"})

# =========================================
# EXECUÇÃO DO PROJETO
# =========================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=True,
        allow_unsafe_werkzeug=True
    )
