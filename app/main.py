# -*- coding: utf-8 -*-
"""
Vendor Daily Check-In - WhatsApp Webhook
Stack : Flask + WhatsApp Cloud API + PostgreSQL
"""
import hashlib
import hmac
import logging
import os

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from sqlalchemy import text

from .conversation import handle_message
from .extensions import db, jwt
from .models import Depot, Product, User
from .repository import append_declaration, claim_message, release_message

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
database_url = os.getenv("DATABASE_URL", "postgresql+psycopg://fanmilk:fanmilk@localhost:5432/fanmilk")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "development-only-secret-key-at-least-32-characters")
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", app.config["SECRET_KEY"])
db.init_app(app)
jwt.init_app(app)
CORS(
    app,
    resources={r"/api/*": {"origins": [item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]}},
    allow_headers=["Content-Type", "Authorization"],
)
allowed_origins = {
    item.strip()
    for item in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if item.strip()
}


@app.after_request
def add_cors_headers(response):
    """Ajoute explicitement les en-tetes requis par les frontends autorises."""
    origin = request.headers.get("Origin")
    if origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers.add("Vary", "Origin")
    return response


from .api import api
app.register_blueprint(api)

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "mon_token_secret")
META_APP_SECRET = os.getenv("META_APP_SECRET")


@app.cli.command("init-db")
def init_db_command():
    """Cree les tables PostgreSQL et les donnees de reference."""
    db.create_all()
    depot_names = ["GERM DOSSEH", "SUPER DEPOT", "NBUKE RAMCO", "NADONIELLA A", "SAINT MARTIN", "YEHONAM"]
    for name in depot_names:
        if not Depot.query.filter_by(name=name).first():
            db.session.add(Depot(name=name, location="Lome, Togo"))
    for sku, name in (("FANXTRA", "FanXtra"), ("FANCHOCO", "FanChoco"), ("FANVANILLE", "FanVanille")):
        if not Product.query.filter_by(sku=sku).first():
            db.session.add(Product(sku=sku, name=name))
    db.session.flush()
    admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if admin_email and admin_password and not User.query.filter_by(email=admin_email).first():
        admin = User(name="Administrateur FanMilk", email=admin_email, role="administrateur")
        admin.set_password(admin_password)
        db.session.add(admin)
    depositaire_email = os.getenv("DEPOSITAIRE_EMAIL", "").strip().lower()
    depositaire_password = os.getenv("DEPOSITAIRE_PASSWORD", "")
    if depositaire_email and depositaire_password and not User.query.filter_by(email=depositaire_email).first():
        depot = Depot.query.filter_by(name=depot_names[0]).first()
        user = User(name="Depositaire GERM DOSSEH", email=depositaire_email, role="depositaire", depot_id=depot.id)
        user.set_password(depositaire_password)
        db.session.add(user)
    db.session.commit()
    print("Base PostgreSQL initialisee.")


def _valid_meta_signature(raw_body, signature):
    if not META_APP_SECRET:
        logger.error("META_APP_SECRET manquant")
        return False
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        META_APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature[7:], expected)


@app.route("/")
def index():
    return (
        "<h1>Vendor Bot</h1>"
        "<p>Available endpoints:</p>"
        "<ul><li><a href='/webhook'>/webhook</a> (GET/POST)</li></ul>",
        200,
    )


@app.route("/healthz")
def healthz():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ok", "database": "connected"}), 200
    except Exception:
        logger.exception("Echec du controle PostgreSQL")
        return jsonify({"status": "error", "database": "unavailable"}), 503


@app.route("/webhook", methods=["GET"])
def verify():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verifie OK")
        return challenge, 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    if not _valid_meta_signature(
        request.get_data(cache=True), request.headers.get("X-Hub-Signature-256")
    ):
        return jsonify({"status": "invalid signature"}), 401

    data = request.get_json(silent=True)
    message_id = None
    try:
        entry   = data["entry"][0]
        changes = entry["changes"][0]["value"]

        # Ignorer les notifications de statut
        if "messages" not in changes:
            return jsonify({"status": "ok"}), 200

        message  = changes["messages"][0]
        message_id = message.get("id")
        if not claim_message(message_id):
            return jsonify({"status": "duplicate"}), 200
        phone    = message["from"]
        msg_type = message.get("type")

        # Texte libre
        if msg_type == "text":
            body = message["text"]["body"].strip()
        # Bouton interactif
        elif msg_type == "interactive":
            itype = message["interactive"].get("type")
            if itype == "button_reply":
                body = message["interactive"]["button_reply"]["id"].strip()
            elif itype == "list_reply":
                body = message["interactive"]["list_reply"]["id"].strip()
            else:
                return jsonify({"status": "ok"}), 200
        else:
            return jsonify({"status": "ok"}), 200

        logger.info("Message recu de {}: {}".format(phone, body))

        # Traiter la conversation
        reply, completed_row = handle_message(phone, body)

        # Envoyer la reponse seulement si elle existe
        if reply:
            from .whatsapp import send_message
            send_message(phone, reply)

        # Enregistrer dans PostgreSQL si le parcours est termine
        if completed_row:
            append_declaration(completed_row)
            logger.info("Declaration enregistree dans PostgreSQL pour {}".format(phone))

    except Exception as e:
        release_message(message_id)
        logger.error("Erreur webhook: {}".format(e), exc_info=True)
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
