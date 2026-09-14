import logging
from concurrent.futures import ThreadPoolExecutor

from .email_service import send_notification_email
from .extensions import db
from .models import Notification, User


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


def notify_users(users, kind, title, message, link="", priority="normale"):
    """Persiste d'abord les alertes, puis tente les canaux externes sans bloquer le bot."""
    users = list({user.id: user for user in users}.values())
    for user in users:
        db.session.add(Notification(
            recipient_user_id=user.id,
            kind=kind,
            title=title,
            message=message,
            priority=priority,
            link=link,
        ))
    db.session.commit()

    recipients = [(user.id, user.email, user.phone) for user in users]

    def dispatch(user_id, email, phone):
        from .whatsapp import send_message
        prefix = "🚨 URGENCE\n\n" if priority == "urgente" else ""
        try:
            send_notification_email(email, title, title, message)
        except Exception:
            logger.exception("Échec notification e-mail utilisateur %s", user_id)
        if phone:
            try:
                send_message(phone, prefix + "*{}*\n\n{}".format(title, message))
            except Exception:
                logger.exception("Échec notification WhatsApp utilisateur %s", user_id)

    for recipient in recipients:
        executor.submit(dispatch, *recipient)
