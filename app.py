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
import os

# =========================================
# APP
# =========================================

app = Flask(__name__)

CORS(app)

app.config["SECRET_KEY"] = "segredo"

app.config["JWT_SECRET_KEY"] = "jwtsegredo"

app.config["SQLALCHEMY_DATABASE_URI"] = \
"sqlite:///uber.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

jwt = JWTManager(app)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)

# =========================================
# MODELS
# =========================================

class User(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    nome = db.Column(
        db.String(120)
    )

    email = db.Column(
        db.String(120),
        unique=True
    )

    senha = db.Column(
        db.Text
    )

    telefone = db.Column(
        db.String(20)
    )

    tipo = db.Column(
        db.String(20)
    )


class Motorista(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer
    )

    carro = db.Column(
        db.String(120)
    )

    placa = db.Column(
        db.String(20)
    )

    foto = db.Column(
        db.String(500)
    )

    online = db.Column(
        db.Boolean,
        default=False
    )


class Corrida(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    passageiro_id = db.Column(
        db.Integer
    )

    motorista_id = db.Column(
        db.Integer,
        nullable=True
    )

    origem = db.Column(
        db.String(255)
    )

    destino = db.Column(
        db.String(255)
    )

    valor = db.Column(
        db.Float
    )

    status = db.Column(
        db.String(50),
        default="pendente"
    )

# =========================================
# CRIAR BANCO
# =========================================

@app.route("/criar_banco")
def criar_banco():

    db.create_all()

    return jsonify({
        "status":"ok"
    })

# =========================================
# REGISTER PASSAGEIRO
# =========================================

@app.route("/register", methods=["POST"])
def register():

    data = request.get_json()

    nome = data.get("nome")
    email = data.get("email")
    senha = data.get("senha")
    telefone = data.get("telefone")
    tipo = data.get("tipo")

    if not nome or not email or not senha:

        return jsonify({
            "erro":"campos obrigatorios"
        }), 400

    if User.query.filter_by(email=email).first():

        return jsonify({
            "erro":"email ja existe"
        }), 400

    user = User(
        nome=nome,
        email=email,
        senha=senha,
        telefone=telefone,
        tipo=tipo
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({
        "status":"criado"
    })

# =========================================
# REGISTER MOTORISTA
# =========================================

@app.route("/registrar_motorista", methods=["POST"])
def registrar_motorista():

    data = request.get_json()

    nome = data.get("nome")
    email = data.get("email")
    senha = data.get("senha")

    carro = data.get("carro")
    placa = data.get("placa")
    foto = data.get("foto")

    if not nome or not email or not senha:

        return jsonify({
            "erro":"campos obrigatorios"
        }), 400

    if User.query.filter_by(email=email).first():

        return jsonify({
            "erro":"email ja existe"
        }), 400

    user = User(
        nome=nome,
        email=email,
        senha=senha,
        tipo="motorista"
    )

    db.session.add(user)
    db.session.commit()

    motorista = Motorista(
        user_id=user.id,
        carro=carro or "Veículo",
        placa=placa or "ABC-0000",
        foto=foto or "https://i.imgur.com/6VBx3io.png",
        online=False
    )

    db.session.add(motorista)
    db.session.commit()

    return jsonify({
        "status":"motorista criado"
    })

# =========================================
# LOGIN
# =========================================

@app.route("/login", methods=["POST"])
def login():

    data = request.get_json()

    user = User.query.filter_by(
        email=data.get("email"),
        senha=data.get("senha")
    ).first()

    if not user:

        return jsonify({
            "erro":"login invalido"
        }), 401

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
# MOTORISTAS ONLINE
# =========================================

@app.route("/motoristas_online")
def motoristas_online():

    motoristas = Motorista.query.filter_by(
        online=True
    ).all()

    lista = []

    for m in motoristas:

        user = User.query.get(m.user_id)

        lista.append({

            "id": m.id,

            "nome": user.nome,

            "carro": m.carro,

            "placa": m.placa,

            "foto": m.foto

        })

    return jsonify(lista)

# =========================================
# FICAR ONLINE
# =========================================

@app.route(
    "/ficar_online/<int:user_id>",
    methods=["POST"]
)
def ficar_online(user_id):

    m = Motorista.query.filter_by(
        user_id=user_id
    ).first()

    if not m:

        m = Motorista(

            user_id=user_id,

            carro="Veículo",

            placa="ABC-0000",

            foto="https://i.imgur.com/6VBx3io.png"

        )

    m.online = True

    db.session.add(m)

    db.session.commit()

    return jsonify({
        "status":"online"
    })

# =========================================
# FICAR OFFLINE
# =========================================

@app.route(
    "/ficar_offline/<int:user_id>",
    methods=["POST"]
)
def ficar_offline(user_id):

    motorista = Motorista.query.filter_by(
        user_id=user_id
    ).first()

    if motorista:

        motorista.online = False

        db.session.commit()

    return jsonify({
        "status":"offline"
    })

# =========================================
# NOVA CORRIDA
# =========================================

@app.route("/nova_corrida", methods=["POST"])
def nova_corrida():

    data = request.get_json()

    corrida = Corrida(

        passageiro_id=data["passageiro_id"],

        origem=data["origem"],

        destino=data["destino"],

        valor=data["valor"],

        status="pendente"

    )

    db.session.add(corrida)

    db.session.commit()

    passageiro = User.query.get(
        corrida.passageiro_id
    )

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

    return jsonify({

        "status":"ok",

        "corrida_id": corrida.id

    })

# =========================================
# ACEITAR CORRIDA
# =========================================

@app.route(
    "/aceitar_corrida/<int:id>",
    methods=["POST"]
)
@jwt_required()
def aceitar_corrida(id):

    user_id = int(
        get_jwt_identity()
    )

    corrida = Corrida.query.get(id)

    if not corrida:

        return jsonify({
            "erro":"corrida nao encontrada"
        })

    corrida.motorista_id = user_id

    corrida.status = "aceita"

    db.session.commit()

    motorista_user = User.query.get(
        user_id
    )

    motorista = Motorista.query.filter_by(
        user_id=user_id
    ).first()

    print("ENVIANDO SOCKET")

    socketio.emit(

        "corrida_aceita",

        {

            "corrida_id": corrida.id,

            "motorista_id": motorista_user.id,

            "motorista_nome": motorista_user.nome,

            "placa": motorista.placa or "ABC-0000",

            "carro": motorista.carro or "Veículo",

            "foto": motorista.foto or "https://i.imgur.com/6VBx3io.png"

        }

    )

    return jsonify({
        "status":"ok"
    })

# =========================================
# CANCELAR CORRIDA
# =========================================

@app.route(
    "/cancelar_corrida/<int:id>",
    methods=["POST"]
)
def cancelar_corrida(id):

    corrida = Corrida.query.get(id)

    if not corrida:

        return jsonify({
            "erro":"corrida nao encontrada"
        })

    corrida.status = "cancelada"

    db.session.commit()

    socketio.emit(

        "corrida_cancelada",

        {

            "corrida_id": corrida.id

        }

    )

    return jsonify({
        "status":"cancelada"
    })

# =========================================
# GPS TEMPO REAL
# =========================================

@app.route(
    "/atualizar_localizacao",
    methods=["POST"]
)
def atualizar_localizacao():

    data = request.get_json()

    motorista_id = data.get(
        "motorista_id"
    )

    latitude = data.get(
        "latitude"
    )

    longitude = data.get(
        "longitude"
    )

    socketio.emit(

        "localizacao_motorista",

        {

            "motorista_id": motorista_id,

            "latitude": latitude,

            "longitude": longitude

        }

    )

    return jsonify({
        "status":"localizacao atualizada"
    })

# =========================================
# RUN
# =========================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    socketio.run(

        app,

        host="0.0.0.0",

        port=port,

        debug=True

    )
