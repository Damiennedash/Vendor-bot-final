import logging
import os
from concurrent.futures import ThreadPoolExecutor

from flask import current_app

from .email_service import email_is_configured, send_notification_email
from .extensions import db
from .models import Notification, User, utc_now


logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fanmilk-alert")


def recipients_for_depot(depot_id, include_admin=True, depositaires_only=False):
    query = User.query.filter(User.active.is_(True))
    if depositaires_only:
        return query.filter(User.role == "depositaire", User.depot_id == depot_id).all()
    roles = ["depositaire"] + (["administrateur"] if include_admin else [])
    return query.filter(
        User.role.in_(roles),
        (User.role == "administrateur") | (User.depot_id == depot_id),
    ).all()


def _deliver(notification_id):
    notification = db.session.get(Notification, notification_id)
    if not notification:
        return
    user = notification.recipient
    prefix = "🚨 URGENCE\n\n" if notification.priority == "urgente" else ""
    errors = []
    email_ok = notification.email_status == "envoye"
    whatsapp_ok = notification.whatsapp_status in {"envoye", "ignore"}
    for attempt in range(1, 4):
        if not email_ok:
            try:
                email_ok = bool(send_notification_email(
                    user.email, notification.title, notification.title, notification.message
                ))
            except Exception as exc:
                errors.append("E-mail: {}".format(str(exc)[:180]))
        if not user.phone:
            whatsapp_ok = True
            notification.whatsapp_status = "ignore"
        elif not whatsapp_ok:
            try:
                from .whatsapp import send_message
                whatsapp_ok = bool(send_message(
                    user.phone,
                    prefix + "*{}*\n\n{}".format(notification.title, notification.message),
                ))
            except Exception as exc:
                errors.append("WhatsApp: {}".format(str(exc)[:180]))
        notification.delivery_attempts += 1
        if email_ok and whatsapp_ok:
            break
    notification.email_status = (
        "envoye" if email_ok else ("non_configure" if not email_is_configured() else "echoue")
    )
    if notification.whatsapp_status != "ignore":
        notification.whatsapp_status = "envoye" if whatsapp_ok else "echoue"
    notification.last_attempt_at = utc_now()
    notification.last_delivery_error = " | ".join(errors[-3:]) or None
    db.session.commit()


def retry_notification(notification_id):
    _deliver(notification_id)


def notify_users(users, kind, title, message, link="", priority="normale"):
    """Persiste les alertes, puis tente trois fois les canaux externes sans bloquer le bot."""
    users = list({user.id: user for user in users}.values())
    rows = []
    for user in users:
        row = Notification(
            recipient_user_id=user.id,
            kind=kind,
            title=title,
            message=message,
            priority=priority,
            link=link,
        )
        db.session.add(row)
        rows.append(row)
    db.session.commit()
    app = current_app._get_current_object()

    def dispatch(notification_id):
        with app.app_context():
            try:
                _deliver(notification_id)
            except Exception:
                logger.exception("Échec notification %s", notification_id)

    for row in rows:
        executor.submit(dispatch, row.id)
