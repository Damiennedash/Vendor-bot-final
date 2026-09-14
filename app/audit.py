from .extensions import db
from .models import AuditLog


def record_audit(actor, action, entity_type, entity_id, description, before=None, after=None):
    """Ajoute une trace métier dans la transaction courante."""
    db.session.add(AuditLog(
        actor_user_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id or ""),
        description=description,
        before_data=before,
        after_data=after,
    ))
