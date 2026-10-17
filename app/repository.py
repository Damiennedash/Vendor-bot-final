from datetime import datetime, time, timedelta, timezone

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


def load_vendor(phone):
    """Charge un profil frais depuis PostgreSQL pour chaque message."""
    vendor = db.session.get(Vendor, phone)
    if vendor is None:
        return None
    return {
        "nom": vendor.name,
        "depot": vendor.depot.name,
        "last_montant": str(vendor.last_sales_amount or 0),
        "last_fanxtra": str(vendor.last_fanxtra or 0),
        "last_fanchoco": str(vendor.last_fanchoco or 0),
        "last_fanvanille": str(vendor.last_fanvanille or 0),
        "last_pieces": str(vendor.last_pieces or 0),
        "last_date": vendor.last_sales_date.strftime("%d/%m/%Y") if vendor.last_sales_date else "",
    }


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


def latest_daily_declaration(phone, sales_date=None):
    day_start = datetime.combine(sales_date or datetime.now().date(), time.min)
    return Sale.query.filter(
        Sale.vendor_phone == phone,
        ((Sale.sales_date == day_start.date()) | (Sale.sales_date.is_(None) & (Sale.declared_at >= day_start) & (Sale.declared_at < day_start + timedelta(days=1)))),
        (Sale.source != "WhatsApp - saisie en cours") | (Sale.status == "rejetee"),
    ).order_by(Sale.declared_at.desc(), Sale.id.desc()).first()


def append_difficulty_followup(row):
    """Record a follow-up without creating another sale or changing its figures."""
    from .notifications import notify_users, recipients_for_depot
    vendor = db.session.get(Vendor, row[3])
    if vendor is None:
        raise ValueError("Revendeur inconnu")
    category = (row[12] or "").strip()
    difficulty = None
    if category and category not in {"-", "Aucun probleme", "Aucun problème"}:
        difficulty = Difficulty(
            vendor_phone=vendor.phone, depot_id=vendor.depot_id,
            category=category, prime_pillar=row[13] or "",
            description=row[14] or "",
            reported_at=datetime.strptime(row[0] + " " + row[1], "%d/%m/%Y %H:%M"),
        )
        db.session.add(difficulty)
        db.session.commit()
    recipients = recipients_for_depot(vendor.depot_id)
    notify_users(
        [user for user in recipients if user.role == "depositaire"],
        "information", "Nouveau suivi Vendor-Bot",
        "{} ({}) a soumis un suivi : {}. {}".format(
            vendor.name, vendor.phone, category, row[14] or ""),
        "/depositaire/difficultes",
    )
    if difficulty:
        notify_users(
            [user for user in recipients if user.role == "administrateur"],
            "difficulte", "Difficulté urgente signalée",
            "{} — {} : {}".format(vendor.name, category, difficulty.description or "Aucun détail"),
            "/dashboard/difficultes", priority="urgente",
        )
    return difficulty.id if difficulty else None


def append_declaration(row):
    if row[15] == "WhatsApp - suivi difficultes":
        return append_difficulty_followup(row)
    declared_at = datetime.strptime("{} {}".format(row[0], row[1]), "%d/%m/%Y %H:%M")
    sales_date = datetime.strptime(row[16], "%d/%m/%Y").date() if len(row) > 16 else declared_at.date()
    depot = get_or_create_depot(row[5])
    vendor = db.session.get(Vendor, row[3])
    if vendor is None:
        vendor = Vendor(phone=row[3], name=row[4], depot_id=depot.id)
        db.session.add(vendor)
        db.session.flush()
    else:
        vendor.name = row[4]
        vendor.depot_id = depot.id
    vendor.last_declaration_at = declared_at

    amount = _integer(row[7])
    quantities = {
        "FANXTRA": _integer(row[8]),
        "FANCHOCO": _integer(row[9]),
        "FANVANILLE": _integer(row[10]),
    }
    day_start = datetime.combine(declared_at.date(), time.min)
    day_end = day_start + timedelta(days=1)
    sale = Sale.query.filter(
        Sale.vendor_phone == vendor.phone,
        Sale.status == "en_attente",
        Sale.source == "WhatsApp - saisie en cours",
        Sale.sales_date == sales_date,
    ).order_by(Sale.id.desc()).first()
    if sale is None:
        sale = Sale(vendor_phone=vendor.phone, status="en_attente")
        db.session.add(sale)
    else:
        for line in list(sale.lines):
            db.session.delete(line)

    sale.sales_date = sales_date
    sale.declared_at = declared_at
    sale.period = row[2]
    sale.depot_id = depot.id
    sale.amount = amount
    sale.location = row[11] or ""
    sale.source = row[15] or "WhatsApp"
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
    difficulty = None
    # Each completed declaration can report a new occurrence, even on the same day.
    if (sale.source != "WhatsApp - saisie en cours"
            and category and category not in {"-", "Aucun probleme", "Aucun problème"}):
        difficulty = Difficulty(
            vendor_phone=vendor.phone,
            depot_id=depot.id,
            category=category,
            prime_pillar=row[13] or "",
            description=row[14] or "",
            reported_at=declared_at,
        )
        db.session.add(difficulty)
    db.session.commit()
    if (row[15] or "") != "WhatsApp - saisie en cours":
        from .notifications import notify_users, recipients_for_depot
        details = ", ".join(
            "{} : {}".format(sku, quantity) for sku, quantity in quantities.items() if quantity > 0
        ) or "Aucun produit déclaré"
        recipients = recipients_for_depot(depot.id)
        sale_message = "{} ({}) a soumis une vente de {:,} FCFA le {}. Produits : {}.".format(
            vendor.name, vendor.phone, amount, declared_at.strftime("%d/%m/%Y à %H:%M"), details
        ).replace(",", " ")
        sale_message += " Date de vente : {}.".format(sales_date.strftime("%d/%m/%Y"))
        notify_users(
            [user for user in recipients if user.role == "depositaire"],
            "vente", "Nouvelle vente Vendor-Bot", sale_message, "/depositaire/ventes",
        )
        if difficulty:
            difficulty_message = "{} — {} : {}".format(
                vendor.name, category, difficulty.description or "Aucun détail"
            )
            notify_users(
                [user for user in recipients if user.role == "administrateur"],
                "difficulte", "Difficulté urgente signalée", difficulty_message,
                "/dashboard/difficultes", priority="urgente",
            )
    return sale.id


def recover_missing_sales():
    """Reconstruit les ventes dont les chiffres ont ete saisis avant une coupure du parcours."""
    recovered = 0
    vendors = Vendor.query.filter(Vendor.last_sales_date.isnot(None)).all()
    for vendor in vendors:
        day_start = datetime.combine(vendor.last_sales_date, time.min)
        day_end = day_start + timedelta(days=1)
        existing = Sale.query.filter(
            Sale.vendor_phone == vendor.phone,
            ((Sale.sales_date == vendor.last_sales_date) | (Sale.sales_date.is_(None) & (Sale.declared_at >= day_start) & (Sale.declared_at < day_end))),
        ).first()
        if existing:
            continue
        row = [
            vendor.last_sales_date.strftime("%d/%m/%Y"),
            "00:00",
            "Matin",
            vendor.phone,
            vendor.name,
            vendor.depot.name,
            "Recuperee apres interruption",
            str(vendor.last_sales_amount or 0),
            str(vendor.last_fanxtra or 0),
            str(vendor.last_fanchoco or 0),
            str(vendor.last_fanvanille or 0),
            "A preciser",
            "-",
            "",
            "",
            "WhatsApp - recuperation automatique",
        ]
        append_declaration(row)
        recovered += 1
    return recovered


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
