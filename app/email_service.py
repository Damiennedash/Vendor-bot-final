import logging
import os
from html import escape

import requests


logger = logging.getLogger(__name__)


def send_password_reset_email(recipient, recipient_name, reset_url):
    """Envoie le lien de récupération via l'API HTTP Resend."""
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY manquante")

    sender = os.getenv(
        "RESET_EMAIL_FROM", "FanMilk Togo <onboarding@resend.dev>"
    ).strip()
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": "Bearer {}".format(api_key),
            "Content-Type": "application/json",
        },
        json={
            "from": sender,
            "to": [recipient],
            "subject": "Réinitialisation de votre mot de passe FanMilk",
            "html": (
                "<p>Bonjour {},</p>"
                "<p>Vous avez demandé à modifier votre mot de passe FanMilk.</p>"
                "<p><a href=\"{}\" style=\"display:inline-block;padding:12px 20px;"
                "background:#0a4ea8;color:#fff;text-decoration:none;border-radius:10px\">"
                "Choisir un nouveau mot de passe</a></p>"
                "<p>Ce lien est valable pendant 30 minutes et ne peut être utilisé qu'une fois.</p>"
                "<p>Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.</p>"
            ).format(escape(recipient_name), escape(reset_url, quote=True)),
        },
        timeout=15,
    )
    response.raise_for_status()
    logger.info("E-mail de récupération envoyé à %s", recipient)
