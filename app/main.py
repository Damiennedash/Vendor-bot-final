# -*- coding: utf-8 -*-
"""
Vendor Daily Check-In - WhatsApp Webhook
Stack : Flask + WhatsApp Cloud API + MySQL
"""
import hashlib
import hmac
import logging
import os

from flask import Flask, request, jsonify
from dotenv import load_dotenv
from sqlalchemy import text

from .conversation import handle_message
from .extensions import db
from .repository import append_declaration, claim_message, release_message

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "mysql+pymysql://fanmilk:fanmilk@localhost:3306/fanmilk"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 280}
db.init_app(app)

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "mon_token_secret")
META_APP_SECRET = os.getenv("META_APP_SECRET")


@app.cli.command("init-db")
def init_db_command():
    """Cree les tables MySQL necessaires."""
    db.create_all()
    print("Base MySQL initialisee.")


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
        logger.exception("Echec du controle MySQL")
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

        # Enregistrer dans MySQL si le parcours est termine
        if completed_row:
            append_declaration(completed_row)
            logger.info("Declaration enregistree dans MySQL pour {}".format(phone))

    except Exception as e:
        release_message(message_id)
        logger.error("Erreur webhook: {}".format(e), exc_info=True)
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
