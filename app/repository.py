from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import BotSession, Declaration, ProcessedMessage, Vendor


def _integer(value, default=0):
    try:
        return int(str(value).replace(" ", "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def load_vendor_memory():
    memory = {}
    for vendor in Vendor.query.all():
        memory[vendor.phone] = {
            "nom": vendor.name,
            "depot": vendor.depot,
            "last_montant": str(vendor.last_sales_amount or 0),
            "last_fanxtra": str(vendor.last_fanxtra or 0),
            "last_fanchoco": str(vendor.last_fanchoco or 0),
            "last_fanvanille": str(vendor.last_fanvanille or 0),
            "last_pieces": str(vendor.last_pieces or 0),
            "last_date": vendor.last_sales_date.strftime("%d/%m/%Y")
            if vendor.last_sales_date
            else "",
        }
    return memory


def save_vendor(phone, nom, depot):
    vendor = db.session.get(Vendor, phone)
    if vendor is None:
        vendor = Vendor(phone=phone, name=nom, depot=depot)
        db.session.add(vendor)
    else:
        vendor.name = nom
        vendor.depot = depot
    vendor.last_declaration_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()


def update_vendor_sales(phone, montant, pieces, date, fanxtra="0", fanchoco="0", fanvanille="0"):
    vendor = db.session.get(Vendor, phone)
    if vendor is None:
        raise ValueError("Vendor inconnu: {}".format(phone))
    vendor.last_sales_amount = _integer(montant)
    vendor.last_pieces = _integer(pieces)
    vendor.last_fanxtra = _integer(fanxtra)
    vendor.last_fanchoco = _integer(fanchoco)
    vendor.last_fanvanille = _integer(fanvanille)
    vendor.last_sales_date = datetime.strptime(date, "%d/%m/%Y").date()
    db.session.commit()


def append_declaration(row):
    declared_at = datetime.strptime("{} {}".format(row[0], row[1]), "%d/%m/%Y %H:%M")
    declaration = Declaration(
        declared_at=declared_at,
        period=row[2],
        vendor_phone=row[3],
        vendor_name=row[4],
        depot=row[5],
        sales_status=row[6],
        sales_amount=_integer(row[7]),
        fanxtra=_integer(row[8]),
        fanchoco=_integer(row[9]),
        fanvanille=_integer(row[10]),
        sales_locations=row[11] or "",
        issue_category=row[12] or "",
        prime_pillar=row[13] or "",
        comment=row[14] or "",
        source=row[15] or "WhatsApp QR",
    )
    db.session.add(declaration)
    db.session.commit()
    return declaration.id


def load_bot_session(phone):
    session = db.session.get(BotSession, phone)
    if session is None:
        return None
    return {"step": session.step, "data": dict(session.data or {})}


def save_bot_session(phone, state):
    session = db.session.get(BotSession, phone)
    if session is None:
        session = BotSession(phone=phone)
        db.session.add(session)
    session.step = state.get("step", "start")
    session.data = dict(state.get("data", {}))
    db.session.commit()


def claim_message(message_id):
    if not message_id:
        return True
    db.session.add(ProcessedMessage(message_id=message_id))
    try:
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        return False


def release_message(message_id):
    if not message_id:
        return
    message = db.session.get(ProcessedMessage, message_id)
    if message is not None:
        db.session.delete(message)
        db.session.commit()
