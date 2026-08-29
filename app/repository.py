from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import (
    BotSession,
    Depot,
    Difficulty,
    ProcessedMessage,
    Product,
    Sale,
    SaleLine,
    Vendor,
)


def _integer(value, default=0):
    try:
        return int(str(value).replace(" ", "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def get_or_create_depot(name, location="Togo"):
    depot = Depot.query.filter_by(name=name).first()
    if depot is None:
        depot = Depot(name=name, location=location)
        db.session.add(depot)
        db.session.flush()
    return depot


def get_or_create_product(sku, name=None):
    product = Product.query.filter_by(sku=sku).first()
    if product is None:
        product = Product(sku=sku, name=name or sku)
        db.session.add(product)
        db.session.flush()
    return product


def load_vendor_memory():
    memory = {}
    for vendor in Vendor.query.all():
        memory[vendor.phone] = {
            "nom": vendor.name,
            "depot": vendor.depot.name,
            "last_montant": str(vendor.last_sales_amount or 0),
            "last_fanxtra": str(vendor.last_fanxtra or 0),
            "last_fanchoco": str(vendor.last_fanchoco or 0),
            "last_fanvanille": str(vendor.last_fanvanille or 0),
            "last_pieces": str(vendor.last_pieces or 0),
            "last_date": vendor.last_sales_date.strftime("%d/%m/%Y") if vendor.last_sales_date else "",
        }
    return memory


def save_vendor(phone, nom, depot):
    depot_row = get_or_create_depot(depot)
    vendor = db.session.get(Vendor, phone)
    if vendor is None:
        vendor = Vendor(phone=phone, name=nom, depot_id=depot_row.id)
        db.session.add(vendor)
    else:
        vendor.name = nom
        vendor.depot_id = depot_row.id
    vendor.last_declaration_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()


def update_vendor_sales(phone, montant, pieces, date, fanxtra="0", fanchoco="0", fanvanille="0"):
    vendor = db.session.get(Vendor, phone)
    if vendor is None:
        raise ValueError("Revendeur inconnu: {}".format(phone))
    vendor.last_sales_amount = _integer(montant)
    vendor.last_pieces = _integer(pieces)
    vendor.last_fanxtra = _integer(fanxtra)
    vendor.last_fanchoco = _integer(fanchoco)
    vendor.last_fanvanille = _integer(fanvanille)
    vendor.last_sales_date = datetime.strptime(date, "%d/%m/%Y").date()
    db.session.commit()


def append_declaration(row):
    declared_at = datetime.strptime("{} {}".format(row[0], row[1]), "%d/%m/%Y %H:%M")
    depot = get_or_create_depot(row[5])
    vendor = db.session.get(Vendor, row[3])
    if vendor is None:
        vendor = Vendor(phone=row[3], name=row[4], depot_id=depot.id)
        db.session.add(vendor)
        db.session.flush()

    amount = _integer(row[7])
    quantities = {
        "FANXTRA": _integer(row[8]),
        "FANCHOCO": _integer(row[9]),
        "FANVANILLE": _integer(row[10]),
    }
    sale = Sale(
        declared_at=declared_at,
        period=row[2],
        vendor_phone=vendor.phone,
        depot_id=depot.id,
        amount=amount,
        location=row[11] or "",
        status="en_attente",
        source=row[15] or "WhatsApp",
    )
    db.session.add(sale)
    db.session.flush()

    total_quantity = sum(quantities.values())
    names = {"FANXTRA": "FanXtra", "FANCHOCO": "FanChoco", "FANVANILLE": "FanVanille"}
    for sku, quantity in quantities.items():
        if quantity <= 0:
            continue
        product = get_or_create_product(sku, names[sku])
        subtotal = round(amount * quantity / total_quantity) if total_quantity else 0
        db.session.add(SaleLine(sale_id=sale.id, product_id=product.id, quantity=quantity, subtotal=subtotal))

    category = (row[12] or "").strip()
    if category and category not in {"-", "Aucun probleme"}:
        db.session.add(Difficulty(
            vendor_phone=vendor.phone,
            depot_id=depot.id,
            category=category,
            prime_pillar=row[13] or "",
            description=row[14] or "",
            reported_at=declared_at,
        ))
    db.session.commit()
    return sale.id


def load_bot_session(phone):
    session = db.session.get(BotSession, phone)
    return None if session is None else {"step": session.step, "data": dict(session.data or {})}


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
