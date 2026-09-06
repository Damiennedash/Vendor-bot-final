from datetime import date, datetime, timedelta
from functools import wraps
import hashlib
import logging
import os
import secrets

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .email_service import send_password_reset_email
from .models import Bonus, Depot, Difficulty, PasswordResetToken, Performance, Sale, Stock, User, Vendor, utc_now


api = Blueprint("api", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapped(*args, **kwargs):
            if get_jwt().get("role") not in roles:
                return jsonify({"error": "Acces interdit"}), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def current_user():
    return db.session.get(User, int(get_jwt_identity()))


def iso(value):
    return value.isoformat() if value else None


def vendor_data(vendor):
    return {"phone": vendor.phone, "name": vendor.name, "active": vendor.active}


def user_data(user):
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role,
        "active": user.active,
        "depot": {"id": user.depot.id, "name": user.depot.name} if user.depot else None,
    }


def month_bounds(value):
    """Retourne le debut du mois demande et celui du mois suivant."""
    try:
        start = datetime.strptime(value or date.today().strftime("%Y-%m"), "%Y-%m")
    except ValueError:
        return None
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1)
    else:
        end = datetime(start.year, start.month + 1, 1)
    return start, end


def computed_performance_rows(depot_id=None, period_value=None):
    bounds = month_bounds(period_value)
    if bounds is None:
        return None
    start, end = bounds
    vendor_query = Vendor.query.filter_by(active=True)
    if depot_id:
        vendor_query = vendor_query.filter_by(depot_id=depot_id)
    vendors = vendor_query.order_by(Vendor.name).all()
    phones = [vendor.phone for vendor in vendors]
    aggregates = {}
    if phones:
        rows = (
            db.session.query(
                Sale.vendor_phone,
                Sale.status,
                func.count(Sale.id),
                func.coalesce(func.sum(Sale.amount), 0),
            )
            .filter(
                Sale.vendor_phone.in_(phones),
                Sale.declared_at >= start,
                Sale.declared_at < end,
            )
            .group_by(Sale.vendor_phone, Sale.status)
            .all()
        )
        for phone, status, count, amount in rows:
            aggregates.setdefault(phone, {})[status] = {
                "count": int(count), "amount": int(amount or 0)
            }

    depot_totals = {}
    depot_vendor_counts = {}
    for vendor in vendors:
        validated = aggregates.get(vendor.phone, {}).get("validee", {})
        depot_totals[vendor.depot_id] = depot_totals.get(vendor.depot_id, 0) + validated.get("amount", 0)
        depot_vendor_counts[vendor.depot_id] = depot_vendor_counts.get(vendor.depot_id, 0) + 1

    result = []
    for vendor in vendors:
        stats = aggregates.get(vendor.phone, {})
        validated = stats.get("validee", {"count": 0, "amount": 0})
        rejected = stats.get("rejetee", {"count": 0, "amount": 0})
        pending = stats.get("en_attente", {"count": 0, "amount": 0})
        processed_count = validated["count"] + rejected["count"]
        score = round(validated["count"] * 100 / processed_count) if processed_count else 0
        average = round(depot_totals.get(vendor.depot_id, 0) / max(depot_vendor_counts.get(vendor.depot_id, 1), 1))
        eligible = score >= 80 and validated["amount"] > average and validated["amount"] > 0
        result.append({
            "vendor": vendor_data(vendor),
            "depot": {"id": vendor.depot.id, "name": vendor.depot.name},
            "period": start.strftime("%Y-%m"),
            "total_sales": validated["amount"],
            "score": score,
            "depot_average": average,
            "validated_sales": validated["count"],
            "rejected_sales": rejected["count"],
            "pending_sales": pending["count"],
            "eligible": eligible,
            "suggested_bonus": round(validated["amount"] * 0.05) if eligible else 0,
        })
    return result


def sale_data(sale):
    return {
        "id": sale.id,
        "vendor": vendor_data(sale.vendor),
        "depot": {"id": sale.depot.id, "name": sale.depot.name},
        "declared_at": iso(sale.declared_at),
        "period": sale.period,
        "amount": sale.amount,
        "location": sale.location,
        "status": sale.status,
        "rejection_reason": sale.rejection_reason,
        "lines": [
            {"sku": line.product.sku, "product": line.product.name, "quantity": line.quantity, "subtotal": line.subtotal}
            for line in sale.lines
        ],
    }


def stock_data(stock):
    return {
        "id": stock.id,
        "vendor": vendor_data(stock.vendor),
        "depot": {"id": stock.depot.id, "name": stock.depot.name},
        "product": {"sku": stock.product.sku, "name": stock.product.name},
        "quantity": stock.quantity,
        "declared_at": iso(stock.declared_at),
        "status": stock.status,
        "rejection_reason": stock.rejection_reason,
    }


def difficulty_data(item):
    return {
        "id": item.id,
        "vendor": vendor_data(item.vendor),
        "depot": {"id": item.depot.id, "name": item.depot.name},
        "category": item.category,
        "prime_pillar": item.prime_pillar,
        "description": item.description,
        "reported_at": iso(item.reported_at),
        "state": item.state,
    }


def performance_data(item):
    return {
        "id": item.id,
        "vendor": vendor_data(item.vendor),
        "depot": {"id": item.depot.id, "name": item.depot.name},
        "period": item.period,
        "total_sales": item.total_sales,
        "score": item.score,
        "validated_sales": item.validated_sales,
        "rejected_sales": item.rejected_sales,
    }


def bonus_data(item):
    return {
        "id": item.id,
        "vendor": vendor_data(item.vendor),
        "depot": {"id": item.depot.id, "name": item.depot.name},
        "period": item.period,
        "amount": item.amount,
        "awarded_at": iso(item.awarded_at),
        "awarded_by": item.awarded_by,
    }


@api.post("/auth/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    user = User.query.filter(func.lower(User.email) == email).first()
    if not user or not user.active or not user.check_password(str(payload.get("password", ""))):
        return jsonify({"error": "Identifiants invalides"}), 401
    token = create_access_token(
        identity=str(user.id),
        additional_claims={"role": user.role, "depot_id": user.depot_id},
    )
    return jsonify({
        "access_token": token,
        "user": {
            "id": user.id, "name": user.name, "email": user.email, "phone": user.phone, "role": user.role,
            "depot": {"id": user.depot.id, "name": user.depot.name, "location": user.depot.location} if user.depot else None,
        },
    })


@api.post("/auth/forgot-password")
def forgot_password():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    user = User.query.filter(func.lower(User.email) == email, User.active.is_(True)).first()
    message = "Si ce compte existe, le lien de réinitialisation vient d'être envoyé. Vérifiez aussi vos spams."

    # La réponse reste volontairement identique pour ne pas révéler les comptes existants.
    if not user:
        return jsonify({"message": message})

    now = utc_now()
    PasswordResetToken.query.filter_by(user_id=user.id, used_at=None).update(
        {"used_at": now}
    )
    raw_token = secrets.token_urlsafe(32)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=now + timedelta(minutes=30),
    )
    db.session.add(reset_token)
    db.session.commit()

    frontend_url = os.getenv(
        "FRONTEND_URL", "https://fanmilk-togo.damiennedash.workers.dev"
    ).rstrip("/")
    reset_url = "{}/reinitialisation?token={}".format(frontend_url, raw_token)
    try:
        send_password_reset_email(user.email, user.name, reset_url)
    except Exception:
        logger.exception("Échec de l'envoi de récupération pour l'utilisateur %s", user.id)
        reset_token.used_at = utc_now()
        db.session.commit()

    return jsonify({"message": message})


@api.post("/auth/reset-password")
def reset_password():
    payload = request.get_json(silent=True) or {}
    raw_token = str(payload.get("token", "")).strip()
    password = str(payload.get("password", ""))
    if len(password) < 8:
        return jsonify({"error": "Le mot de passe doit contenir au moins 8 caractères"}), 400
    if not raw_token:
        return jsonify({"error": "Lien de réinitialisation invalide ou expiré"}), 400

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    reset_token = PasswordResetToken.query.filter_by(
        token_hash=token_hash, used_at=None
    ).first()
    if not reset_token or reset_token.expires_at < utc_now() or not reset_token.user.active:
        return jsonify({"error": "Lien de réinitialisation invalide ou expiré"}), 400

    reset_token.user.set_password(password)
    reset_token.used_at = utc_now()
    db.session.commit()
    return jsonify({"message": "Mot de passe modifié. Vous pouvez maintenant vous connecter."})


@api.get("/me")
@jwt_required()
def me():
    user = current_user()
    if not user or not user.active:
        return jsonify({"error": "Compte inactif"}), 401
    return jsonify({
        "id": user.id, "name": user.name, "email": user.email, "phone": user.phone, "role": user.role,
        "depot": {"id": user.depot.id, "name": user.depot.name, "location": user.depot.location} if user.depot else None,
    })


@api.patch("/me")
@jwt_required()
def update_me():
    user = current_user()
    if not user or not user.active:
        return jsonify({"error": "Compte inactif"}), 401

    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", user.name)).strip()
    email = str(payload.get("email", user.email)).strip().lower()
    phone = str(payload.get("phone", user.phone or "")).strip() or None
    password = str(payload.get("password", ""))

    if not name or not email:
        return jsonify({"error": "Le nom et l'adresse electronique sont obligatoires"}), 400
    duplicate = User.query.filter(func.lower(User.email) == email, User.id != user.id).first()
    if duplicate:
        return jsonify({"error": "Cette adresse existe deja"}), 409
    if phone and User.query.filter(User.phone == phone, User.id != user.id).first():
        return jsonify({"error": "Ce numero de telephone existe deja"}), 409
    if password and len(password) < 8:
        return jsonify({"error": "Le nouveau mot de passe doit contenir au moins 8 caracteres"}), 400

    user.name = name
    user.email = email
    user.phone = phone
    if password:
        user.set_password(password)
    db.session.commit()
    return jsonify({
        "id": user.id, "name": user.name, "email": user.email, "phone": user.phone, "role": user.role,
        "depot": {"id": user.depot.id, "name": user.depot.name, "location": user.depot.location} if user.depot else None,
    })


@api.get("/depositaire/summary")
@role_required("depositaire")
def depositaire_summary():
    depot_id = current_user().depot_id
    pending_sales = Sale.query.filter_by(depot_id=depot_id, status="en_attente").count()
    pending_stocks = Stock.query.filter_by(depot_id=depot_id, status="en_attente").count()
    today_sales = db.session.scalar(db.select(func.coalesce(func.sum(Sale.amount), 0)).where(
        Sale.depot_id == depot_id, Sale.status == "validee", func.date(Sale.declared_at) == date.today()
    ))
    active_vendors = Vendor.query.filter_by(depot_id=depot_id, active=True).count()
    return jsonify({"pending_sales": pending_sales, "pending_stocks": pending_stocks, "today_revenue": today_sales, "active_vendors": active_vendors})


@api.get("/depositaire/sales")
@role_required("depositaire")
def depositaire_sales():
    query = Sale.query.filter_by(depot_id=current_user().depot_id)
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    return jsonify([sale_data(item) for item in query.order_by(Sale.declared_at.desc()).all()])


@api.patch("/depositaire/sales/<int:sale_id>")
@role_required("depositaire")
def review_sale(sale_id):
    user = current_user()
    sale = Sale.query.filter_by(id=sale_id, depot_id=user.depot_id).first_or_404()
    if sale.status != "en_attente":
        return jsonify({"error": "Cette vente a deja ete traitee"}), 409
    payload = request.get_json(silent=True) or {}
    action = payload.get("action")
    reason = str(payload.get("reason", "")).strip()
    if action not in {"validate", "reject"}:
        return jsonify({"error": "Action invalide"}), 400
    if action == "reject" and not reason:
        return jsonify({"error": "Le motif de rejet est obligatoire"}), 400
    sale.status = "validee" if action == "validate" else "rejetee"
    sale.rejection_reason = reason or None
    sale.reviewed_at = utc_now()
    sale.reviewed_by = user.id
    db.session.commit()
    message = "Votre vente a ete validee." if action == "validate" else "Votre vente a ete rejetee. Motif : " + reason
    from .whatsapp import send_message
    send_message(sale.vendor_phone, message)
    return jsonify(sale_data(sale))


@api.get("/depositaire/stocks")
@role_required("depositaire")
def depositaire_stocks():
    query = Stock.query.filter_by(depot_id=current_user().depot_id)
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    return jsonify([stock_data(item) for item in query.order_by(Stock.declared_at.desc()).all()])


@api.patch("/depositaire/stocks/<int:stock_id>")
@role_required("depositaire")
def review_stock(stock_id):
    user = current_user()
    stock = Stock.query.filter_by(id=stock_id, depot_id=user.depot_id).first_or_404()
    if stock.status != "en_attente":
        return jsonify({"error": "Ce stock a deja ete traite"}), 409
    payload = request.get_json(silent=True) or {}
    action = payload.get("action")
    reason = str(payload.get("reason", "")).strip()
    if action not in {"validate", "reject"}:
        return jsonify({"error": "Action invalide"}), 400
    if action == "reject" and not reason:
        return jsonify({"error": "Le motif de rejet est obligatoire"}), 400
    stock.status = "valide" if action == "validate" else "rejete"
    stock.rejection_reason = reason or None
    stock.reviewed_at = utc_now()
    stock.reviewed_by = user.id
    db.session.commit()
    message = "Votre stock a ete valide." if action == "validate" else "Votre stock a ete rejete. Motif : " + reason
    from .whatsapp import send_message
    send_message(stock.vendor_phone, message)
    return jsonify(stock_data(stock))


@api.get("/depositaire/performances")
@role_required("depositaire")
def depositaire_performances():
    rows = computed_performance_rows(
        depot_id=current_user().depot_id,
        period_value=request.args.get("period"),
    )
    if rows is None:
        return jsonify({"error": "Periode invalide, format attendu AAAA-MM"}), 400
    return jsonify(rows)


@api.get("/depositaire/bonuses")
@role_required("depositaire")
def depositaire_bonuses():
    rows = Bonus.query.filter_by(depot_id=current_user().depot_id).order_by(Bonus.awarded_at.desc()).all()
    return jsonify([bonus_data(item) for item in rows])


@api.get("/depositaire/difficulties")
@role_required("depositaire")
def depositaire_difficulties():
    rows = Difficulty.query.filter_by(depot_id=current_user().depot_id).order_by(Difficulty.reported_at.desc()).all()
    return jsonify([difficulty_data(item) for item in rows])


@api.get("/depositaire/history")
@role_required("depositaire")
def depositaire_history():
    depot_id = current_user().depot_id
    sales = Sale.query.filter(Sale.depot_id == depot_id, Sale.status != "en_attente").order_by(Sale.declared_at.desc()).all()
    stocks = Stock.query.filter(Stock.depot_id == depot_id, Stock.status != "en_attente").order_by(Stock.declared_at.desc()).all()
    return jsonify({"sales": [sale_data(item) for item in sales], "stocks": [stock_data(item) for item in stocks]})


@api.get("/admin/summary")
@role_required("administrateur")
def admin_summary():
    bounds = month_bounds(request.args.get("period"))
    if bounds is None:
        return jsonify({"error": "Periode invalide, format attendu AAAA-MM"}), 400
    start, end = bounds
    depot_id = request.args.get("depot_id")
    revenue_query = db.select(func.coalesce(func.sum(Sale.amount), 0)).where(
        Sale.status == "validee", Sale.declared_at >= start, Sale.declared_at < end
    )
    vendors_query = Vendor.query.filter_by(active=True)
    difficulties_query = Difficulty.query.filter(
        Difficulty.state != "resolue", Difficulty.reported_at >= start, Difficulty.reported_at < end
    )
    bonuses_query = db.select(func.coalesce(func.sum(Bonus.amount), 0)).where(
        Bonus.awarded_at >= start, Bonus.awarded_at < end
    )
    if depot_id:
        revenue_query = revenue_query.where(Sale.depot_id == depot_id)
        vendors_query = vendors_query.filter_by(depot_id=depot_id)
        difficulties_query = difficulties_query.filter_by(depot_id=depot_id)
        bonuses_query = bonuses_query.where(Bonus.depot_id == depot_id)
    return jsonify({
        "active_vendors": vendors_query.count(),
        "validated_revenue": db.session.scalar(revenue_query),
        "open_difficulties": difficulties_query.count(),
        "awarded_bonuses": db.session.scalar(bonuses_query),
    })


@api.get("/admin/users")
@role_required("administrateur")
def list_users():
    return jsonify([user_data(item) for item in User.query.order_by(User.name).all()])


@api.get("/admin/vendors")
@role_required("administrateur")
def list_vendors():
    query = Vendor.query
    if request.args.get("depot_id"):
        query = query.filter_by(depot_id=request.args["depot_id"])
    rows = query.order_by(Vendor.name).all()
    phones = [item.phone for item in rows]
    sale_counts = dict(
        db.session.query(Sale.vendor_phone, func.count(Sale.id))
        .filter(Sale.vendor_phone.in_(phones))
        .group_by(Sale.vendor_phone)
        .all()
    ) if phones else {}
    return jsonify([{
        **vendor_data(item),
        "depot": {"id": item.depot.id, "name": item.depot.name},
        "last_declaration_at": iso(item.last_declaration_at),
        "last_sales_amount": item.last_sales_amount,
        "sales_count": sale_counts.get(item.phone, 0),
    } for item in rows])


@api.post("/admin/users")
@role_required("administrateur")
def create_user():
    payload = request.get_json(silent=True) or {}
    role = payload.get("role")
    depot_id = payload.get("depot_id")
    phone = str(payload.get("phone", "")).strip() or None
    if role not in {"administrateur", "depositaire", "revendeur"}:
        return jsonify({"error": "Role invalide"}), 400
    if role in {"depositaire", "revendeur"} and not depot_id:
        return jsonify({"error": "Le depot est obligatoire pour ce role"}), 400
    if role == "revendeur" and not phone:
        return jsonify({"error": "Le telephone est obligatoire pour un revendeur"}), 400
    if not all(payload.get(key) for key in ("name", "email", "password")):
        return jsonify({"error": "Nom, email et mot de passe sont obligatoires"}), 400
    if User.query.filter(func.lower(User.email) == str(payload["email"]).lower()).first():
        return jsonify({"error": "Cette adresse existe deja"}), 409
    if phone and User.query.filter_by(phone=phone).first():
        return jsonify({"error": "Ce numero de telephone existe deja"}), 409
    user = User(
        name=payload["name"],
        email=str(payload["email"]).lower(),
        phone=phone if role == "revendeur" else None,
        role=role,
        depot_id=depot_id,
    )
    user.set_password(payload["password"])
    db.session.add(user)
    if role == "revendeur":
        vendor = db.session.get(Vendor, user.phone)
        if vendor is None:
            db.session.add(Vendor(phone=user.phone, name=user.name, depot_id=depot_id))
        else:
            vendor.name = user.name
            vendor.depot_id = depot_id
            vendor.active = True
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Cette adresse ou ce numero existe deja"}), 409
    return jsonify({"id": user.id}), 201


@api.patch("/admin/users/<int:user_id>")
@role_required("administrateur")
def update_user(user_id):
    user = db.session.get(User, user_id) or User.query.filter_by(id=user_id).first_or_404()
    payload = request.get_json(silent=True) or {}
    original_vendor = db.session.get(Vendor, user.phone) if user.role == "revendeur" and user.phone else None
    role = payload.get("role", user.role)
    name = str(payload.get("name", user.name)).strip()
    email = str(payload.get("email", user.email)).strip().lower()
    depot_id = payload.get("depot_id", user.depot_id)
    phone = str(payload.get("phone", user.phone or "")).strip() or None
    active = bool(payload.get("active", user.active))

    if role not in {"administrateur", "depositaire", "revendeur"}:
        return jsonify({"error": "Role invalide"}), 400
    if not name or not email:
        return jsonify({"error": "Le nom et l'adresse electronique sont obligatoires"}), 400
    if role in {"depositaire", "revendeur"} and not depot_id:
        return jsonify({"error": "Le depot est obligatoire pour ce role"}), 400
    if role == "revendeur" and not phone:
        return jsonify({"error": "Le telephone est obligatoire pour un revendeur"}), 400
    if User.query.filter(func.lower(User.email) == email, User.id != user.id).first():
        return jsonify({"error": "Cette adresse existe deja"}), 409
    if phone and User.query.filter(User.phone == phone, User.id != user.id).first():
        return jsonify({"error": "Ce numero de telephone existe deja"}), 409
    if user.role == "revendeur" and user.phone and phone != user.phone:
        return jsonify({"error": "Le numero WhatsApp d'un revendeur deja cree ne peut pas etre remplace"}), 400

    user.name = name
    user.email = email
    user.role = role
    user.depot_id = None if role == "administrateur" else depot_id
    user.phone = phone if role == "revendeur" else None
    user.active = active
    if payload.get("password"):
        user.set_password(payload["password"])
    if user.role == "revendeur":
        vendor = db.session.get(Vendor, user.phone)
        if vendor is None:
            vendor = Vendor(phone=user.phone)
            db.session.add(vendor)
        vendor.name = user.name
        vendor.depot_id = user.depot_id
        vendor.active = user.active
    elif original_vendor is not None:
        original_vendor.active = False
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Cette adresse ou ce numero existe deja"}), 409
    return jsonify(user_data(user))


@api.get("/admin/performances")
@role_required("administrateur")
def admin_performances():
    rows = computed_performance_rows(
        depot_id=request.args.get("depot_id"),
        period_value=request.args.get("period"),
    )
    if rows is None:
        return jsonify({"error": "Periode invalide, format attendu AAAA-MM"}), 400
    return jsonify(rows)


@api.route("/admin/bonuses", methods=["GET", "POST"])
@role_required("administrateur")
def admin_bonuses():
    if request.method == "GET":
        return jsonify([bonus_data(item) for item in Bonus.query.order_by(Bonus.awarded_at.desc()).all()])
    payload = request.get_json(silent=True) or {}
    vendor = db.session.get(Vendor, payload.get("vendor_phone"))
    if not vendor or not payload.get("period") or int(payload.get("amount", 0)) <= 0:
        return jsonify({"error": "Revendeur, periode et montant positif sont obligatoires"}), 400
    item = Bonus(vendor_phone=vendor.phone, depot_id=vendor.depot_id, period=payload["period"], amount=int(payload["amount"]), awarded_by=current_user().id)
    db.session.add(item)
    db.session.commit()
    from .whatsapp import send_message
    send_message(vendor.phone, "Une prime de {} FCFA vous a ete attribuee pour {}.".format(item.amount, item.period))
    return jsonify(bonus_data(item)), 201


@api.get("/admin/difficulties")
@role_required("administrateur")
def admin_difficulties():
    query = Difficulty.query
    if request.args.get("depot_id"):
        query = query.filter_by(depot_id=request.args["depot_id"])
    return jsonify([difficulty_data(item) for item in query.order_by(Difficulty.reported_at.desc()).all()])


@api.patch("/admin/difficulties/<int:item_id>")
@role_required("administrateur")
def update_difficulty(item_id):
    item = db.session.get(Difficulty, item_id) or Difficulty.query.filter_by(id=item_id).first_or_404()
    state = (request.get_json(silent=True) or {}).get("state")
    allowed = {"ouverte": "en_cours", "en_cours": "resolue"}
    if allowed.get(item.state) != state:
        return jsonify({"error": "Transition d'etat invalide"}), 400
    item.state = state
    db.session.commit()
    return jsonify(difficulty_data(item))


@api.get("/admin/sales")
@role_required("administrateur")
def admin_sales():
    query = Sale.query
    if request.args.get("depot_id"):
        query = query.filter_by(depot_id=request.args["depot_id"])
    return jsonify([sale_data(item) for item in query.order_by(Sale.declared_at.desc()).all()])


@api.get("/admin/stocks")
@role_required("administrateur")
def admin_stocks():
    query = Stock.query
    if request.args.get("depot_id"):
        query = query.filter_by(depot_id=request.args["depot_id"])
    return jsonify([stock_data(item) for item in query.order_by(Stock.declared_at.desc()).all()])


@api.get("/admin/depots")
@role_required("administrateur")
def list_depots():
    return jsonify([{"id": item.id, "name": item.name, "location": item.location} for item in Depot.query.order_by(Depot.name).all()])
