from flask import Flask, request, jsonify
from flask_cors import CORS

from flask_sqlalchemy import SQLAlchemy

from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)

from flask_socketio import SocketIO, emit

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from datetime import datetime

# =========================================
# CONFIG
# =========================================

app = Flask(__name__)

CORS(app)

app.config["SECRET_KEY"] = "segredo"

app.config["JWT_SECRET_KEY"] = "jwtsegredo"

#app.config["SQLALCHEMY_DATABASE_URI"] = \
#"postgresql://postgres:senha@localhost/uber_app"

app.config["SQLALCHEMY_DATABASE_URI"] = \
"sqlite:///uber.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

jwt = JWTManager(app)

socketio = SocketIO(
    app,
    cors_allowed_origins="*"
)

# =========================================
# MODELS
# =========================================

class User(db.Model):

    __tablename__ = "users"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    nome = db.Column(
        db.String(120),
        nullable=False
    )

    email = db.Column(
        db.String(120),
        unique=True
    )

    senha = db.Column(
        db.Text,
        nullable=False
    )

    telefone = db.Column(
        db.String(20)
    )

    tipo = db.Column(
        db.String(20)
    )

    criado_em = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


class Motorista(db.Model):

    __tablename__ = "motoristas"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    carro = db.Column(
        db.String(120)
    )

    placa = db.Column(
        db.String(20)
    )

    latitude = db.Column(
        db.Float,
        default=0
    )

    longitude = db.Column(
        db.Float,
        default=0
    )

    online = db.Column(
        db.Boolean,
        default=False
    )

    avaliacao = db.Column(
        db.Float,
        default=5
    )


class Corrida(db.Model):

    __tablename__ = "corridas"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    passageiro_id = db.Column(
        db.Integer
    )

    motorista_id = db.Column(
        db.Integer
    )

    origem = db.Column(
        db.Text
    )

    destino = db.Column(
        db.Text
    )

    valor = db.Column(
        db.Float
    )

    status = db.Column(
        db.String(50),
        default="procurando"
    )

    criado_em = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

# =========================================
# HOME
# =========================================

@app.route("/")
def home():

    return jsonify({
        "status": "online"
    })

# =========================================
# REGISTER
# =========================================

@app.route("/register", methods=["POST"])
def register():

    data = request.json

    existe = User.query.filter_by(
        email=data["email"]
    ).first()

    if existe:

        return jsonify({
            "erro": "Email já cadastrado"
        })

    senha_hash = generate_password_hash(
        data["senha"]
    )

    novo = User(
        nome=data["nome"],
        email=data["email"],
        senha=senha_hash,
        telefone=data["telefone"],
        tipo=data["tipo"]
    )

    db.session.add(novo)

    db.session.commit()

    # se for motorista
    if data["tipo"] == "motorista":

        motorista = Motorista(
            user_id=novo.id,
            carro=data.get("carro"),
            placa=data.get("placa")
        )

        db.session.add(motorista)

        db.session.commit()

    return jsonify({
        "status": "conta criada"
    })

# =========================================
# LOGIN
# =========================================

@app.route("/login", methods=["POST"])
def login():

    data = request.json

    user = User.query.filter_by(
        email=data["email"]
    ).first()

    if not user:

        return jsonify({
            "erro": "Usuário não encontrado"
        })

    if not check_password_hash(
        user.senha,
        data["senha"]
    ):

        return jsonify({
            "erro": "Senha inválida"
        })

    token = create_access_token(
        identity=str(user.id)
    )

    return jsonify({

        "token": token,

        "user": {

            "id": user.id,

            "nome": user.nome,

            "tipo": user.tipo
        }
    })

# =========================================
# PERFIL
# =========================================

@app.route("/perfil")
@jwt_required()
def perfil():

    user_id = get_jwt_identity()

    user = User.query.get(user_id)

    return jsonify({

        "id": user.id,

        "nome": user.nome,

        "email": user.email,

        "tipo": user.tipo
    })

# =========================================
# SOLICITAR CORRIDA
# =========================================

@app.route("/solicitar_corrida", methods=["POST"])
@jwt_required()
def solicitar_corrida():

    user_id = get_jwt_identity()

    data = request.json

    corrida = Corrida(

        passageiro_id=user_id,

        origem=data["origem"],

        destino=data["destino"],

        valor=data["valor"],

        status="procurando"
    )

    db.session.add(corrida)

    db.session.commit()

    socketio.emit(
        "nova_corrida",
        {
            "corrida_id": corrida.id,
            "origem": corrida.origem,
            "destino": corrida.destino,
            "valor": corrida.valor
        }
    )

    return jsonify({
        "status": "corrida solicitada"
    })

# =========================================
# ACEITAR CORRIDA
# =========================================

@app.route("/aceitar_corrida/<int:id>", methods=["POST"])
@jwt_required()
def aceitar_corrida(id):

    user_id = get_jwt_identity()

    corrida = Corrida.query.get(id)

    if not corrida:

        return jsonify({
            "erro": "Corrida não encontrada"
        })

    corrida.motorista_id = user_id

    corrida.status = "aceita"

    db.session.commit()

    socketio.emit(
        "corrida_aceita",
        {
            "corrida_id": corrida.id,
            "motorista_id": user_id
        }
    )

    return jsonify({
        "status": "corrida aceita"
    })

# =========================================
# FINALIZAR CORRIDA
# =========================================

@app.route("/finalizar_corrida/<int:id>", methods=["POST"])
@jwt_required()
def finalizar_corrida(id):

    corrida = Corrida.query.get(id)

    if not corrida:

        return jsonify({
            "erro": "Corrida não encontrada"
        })

    corrida.status = "finalizada"

    db.session.commit()

    socketio.emit(
        "corrida_finalizada",
        {
            "corrida_id": corrida.id
        }
    )

    return jsonify({
        "status": "corrida finalizada"
    })

# =========================================
# LISTAR CORRIDAS
# =========================================

@app.route("/corridas")
@jwt_required()
def corridas():

    lista = Corrida.query.order_by(
        Corrida.id.desc()
    ).all()

    resultado = []

    for c in lista:

        resultado.append({

            "id": c.id,

            "origem": c.origem,

            "destino": c.destino,

            "valor": c.valor,

            "status": c.status
        })

    return jsonify(resultado)

# =========================================
# MOTORISTAS ONLINE
# =========================================

motoristas_online = {}

# =========================================
# SOCKET GPS
# =========================================

@socketio.on("atualizar_localizacao")
def atualizar_localizacao(data):

    motorista_id = data["motorista_id"]

    latitude = data["latitude"]

    longitude = data["longitude"]

    motoristas_online[motorista_id] = {

        "latitude": latitude,

        "longitude": longitude
    }

    motorista = Motorista.query.filter_by(
        user_id=motorista_id
    ).first()

    if motorista:

        motorista.latitude = latitude

        motorista.longitude = longitude

        motorista.online = True

        db.session.commit()

    emit(
        "motorista_movendo",
        {
            "motorista_id": motorista_id,
            "latitude": latitude,
            "longitude": longitude
        },
        broadcast=True
    )

# =========================================
# LISTAR MOTORISTAS
# =========================================

@app.route("/motoristas_online")
def listar_motoristas():

    return jsonify(
        motoristas_online
    )

# =========================================
# CRIAR BANCO
# =========================================

@app.route("/criar_banco")
def criar_banco():
    with app.app_context():
    db.create_all()

    return jsonify({
        "status": "banco criado"
    })

# =========================================
# RUN
# =========================================

if __name__ == "__main__":

    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=True
    )
