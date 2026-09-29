import logging
import os
import smtplib
from email.message import EmailMessage
from html import escape

import requests


logger = logging.getLogger(__name__)


def get_brevo_config():
    """Return the HTTPS Brevo transport used on Render's free plan."""
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    sender_email = os.getenv("BREVO_SENDER_EMAIL", "").strip()
    if not api_key or not sender_email:
        return None
    return {
        "api_key": api_key,
        "sender_email": sender_email,
        "sender_name": os.getenv("BREVO_SENDER_NAME", "FanMilk Togo").strip()
        or "FanMilk Togo",
    }


def get_email_api_key():
    """Return the Resend key, including the Render-specific fallback name."""
    return (
        os.getenv("RESEND_API_KEY", "").strip()
        or os.getenv("FANMILK_EMAIL_API_KEY", "").strip()
    )


def get_smtp_config():
    """Return SMTP settings without exposing the password to callers or logs."""
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").replace(" ", "").strip()
    if not username or not password:
        return None
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com",
        "port": int(os.getenv("SMTP_PORT", "587").strip() or "587"),
        "username": username,
        "password": password,
        "sender": os.getenv("SMTP_FROM", "FanMilk Togo <{}>".format(username)).strip(),
    }


def email_is_configured():
    return bool(get_brevo_config() or get_smtp_config() or get_email_api_key())


def _send_via_brevo(recipient, subject, html):
    config = get_brevo_config()
    if not config:
        return False
    response = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "api-key": config["api_key"],
            "accept": "application/json",
            "content-type": "application/json",
        },
        json={
            "sender": {
                "name": config["sender_name"],
                "email": config["sender_email"],
            },
            "to": [{"email": recipient}],
            "subject": subject,
            "htmlContent": html,
        },
        timeout=15,
    )
    response.raise_for_status()
    return True


def _send_via_smtp(recipient, subject, html):
    config = get_smtp_config()
    if not config:
        return False

    message = EmailMessage()
    message["From"] = config["sender"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content("Ce message FanMilk nécessite un client de messagerie compatible HTML.")
    message.add_alternative(html, subtype="html")

    with smtplib.SMTP(config["host"], config["port"], timeout=15) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(config["username"], config["password"])
        smtp.send_message(message)
    return True


def _send_via_resend(recipient, subject, html, sender_env):
    api_key = get_email_api_key()
    if not api_key:
        return False
    sender = os.getenv(
        sender_env,
        os.getenv("RESET_EMAIL_FROM", "FanMilk Togo <onboarding@resend.dev>"),
    ).strip()
    response = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": "Bearer {}".format(api_key), "Content-Type": "application/json"},
        json={"from": sender, "to": [recipient], "subject": subject, "html": html},
        timeout=15,
    )
    response.raise_for_status()
    return True


def _send_email(recipient, subject, html, sender_env):
    # Render's free plan blocks SMTP ports. Prefer Brevo's HTTPS API when configured,
    # then retain Gmail SMTP and Resend for compatible hosting environments.
    if get_brevo_config():
        return _send_via_brevo(recipient, subject, html)
    if get_smtp_config():
        return _send_via_smtp(recipient, subject, html)
    return _send_via_resend(recipient, subject, html, sender_env)


def send_notification_email(recipient, subject, title, message):
    """Envoie une notification métier via Gmail SMTP ou Resend."""
    if not email_is_configured():
        logger.warning("Notification e-mail ignorée : aucun transport configuré")
        return False
    return _send_email(
        recipient,
        subject,
        "<h2>{}</h2><p>{}</p>".format(
            escape(title), escape(message).replace("\n", "<br>")
        ),
        "NOTIFICATION_EMAIL_FROM",
    )


def send_password_reset_email(recipient, recipient_name, reset_url):
    """Envoie le lien de récupération via Gmail SMTP ou Resend."""
    if not email_is_configured():
        raise RuntimeError("Aucun transport e-mail configuré")

    _send_email(
        recipient,
        "Réinitialisation de votre mot de passe FanMilk",
        (
            "<p>Bonjour {},</p>"
            "<p>Vous avez demandé à modifier votre mot de passe FanMilk.</p>"
            "<p><a href=\"{}\" style=\"display:inline-block;padding:12px 20px;"
            "background:#0a4ea8;color:#fff;text-decoration:none;border-radius:10px\">"
            "Choisir un nouveau mot de passe</a></p>"
            "<p>Ce lien est valable pendant 30 minutes et ne peut être utilisé qu'une fois.</p>"
            "<p>Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.</p>"
        ).format(escape(recipient_name), escape(reset_url, quote=True)),
        "RESET_EMAIL_FROM",
    )
    logger.info("E-mail de récupération envoyé à %s", recipient)
