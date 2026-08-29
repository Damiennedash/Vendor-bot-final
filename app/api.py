from datetime import date, datetime
from functools import wraps

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import func

from .extensions import db
from .models import Bonus, Depot, Difficulty, Performance, Sale, Stock, User, Vendor, utc_now


api = Blueprint("api", __name__, url_prefix="/api")


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
            "id": user.id, "name": user.name, "email": user.email, "role": user.role,
            "depot": {"id": user.depot.id, "name": user.depot.name, "location": user.depot.location} if user.depot else None,
        },
    })


@api.post("/auth/forgot-password")
def forgot_password():
    # Reponse volontairement identique, que le compte existe ou non.
    return jsonify({"message": "Si ce compte existe, les instructions de reinitialisation seront envoyees."})


@api.get("/me")
@jwt_required()
def me():
    user = current_user()
    if not user or not user.active:
        return jsonify({"error": "Compte inactif"}), 401
    return jsonify({
        "id": user.id, "name": user.name, "email": user.email, "role": user.role,
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
    rows = Performance.query.filter_by(depot_id=current_user().depot_id).all()
    return jsonify([performance_data(item) for item in rows])


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
    revenue = db.session.scalar(db.select(func.coalesce(func.sum(Sale.amount), 0)).where(Sale.status == "validee"))
    return jsonify({
        "active_vendors": Vendor.query.filter_by(active=True).count(),
        "validated_revenue": revenue,
        "open_difficulties": Difficulty.query.filter(Difficulty.state != "resolue").count(),
        "awarded_bonuses": db.session.scalar(db.select(func.coalesce(func.sum(Bonus.amount), 0))),
    })


@api.get("/admin/users")
@role_required("administrateur")
def list_users():
    return jsonify([{
            "id": item.id, "name": item.name, "email": item.email, "phone": item.phone, "role": item.role, "active": item.active,
        "depot": {"id": item.depot.id, "name": item.depot.name} if item.depot else None,
    } for item in User.query.order_by(User.name).all()])


@api.post("/admin/users")
@role_required("administrateur")
def create_user():
    payload = request.get_json(silent=True) or {}
    role = payload.get("role")
    depot_id = payload.get("depot_id")
    if role not in {"administrateur", "depositaire", "revendeur"}:
        return jsonify({"error": "Role invalide"}), 400
    if role in {"depositaire", "revendeur"} and not depot_id:
        return jsonify({"error": "Le depot est obligatoire pour ce role"}), 400
    if role == "revendeur" and not str(payload.get("phone", "")).strip():
        return jsonify({"error": "Le telephone est obligatoire pour un revendeur"}), 400
    if not all(payload.get(key) for key in ("name", "email", "password")):
        return jsonify({"error": "Nom, email et mot de passe sont obligatoires"}), 400
    if User.query.filter(func.lower(User.email) == str(payload["email"]).lower()).first():
        return jsonify({"error": "Cette adresse existe deja"}), 409
    user = User(name=payload["name"], email=str(payload["email"]).lower(), phone=str(payload.get("phone", "")).strip() or None, role=role, depot_id=depot_id)
    user.set_password(payload["password"])
    db.session.add(user)
    if role == "revendeur":
        vendor = db.session.get(Vendor, user.phone)
        if vendor is None:
            db.session.add(Vendor(phone=user.phone, name=user.name, depot_id=depot_id))
    db.session.commit()
    return jsonify({"id": user.id}), 201


@api.patch("/admin/users/<int:user_id>")
@role_required("administrateur")
def update_user(user_id):
    user = db.session.get(User, user_id) or User.query.filter_by(id=user_id).first_or_404()
    payload = request.get_json(silent=True) or {}
    for field in ("name", "email", "phone", "role", "depot_id", "active"):
        if field in payload:
            setattr(user, field, payload[field])
    if payload.get("password"):
        user.set_password(payload["password"])
    if user.role in {"depositaire", "revendeur"} and not user.depot_id:
        return jsonify({"error": "Le depot est obligatoire pour ce role"}), 400
    if user.role == "revendeur" and not user.phone:
        return jsonify({"error": "Le telephone est obligatoire pour un revendeur"}), 400
    db.session.commit()
    return jsonify({"id": user.id, "active": user.active})


@api.get("/admin/performances")
@role_required("administrateur")
def admin_performances():
    query = Performance.query
    if request.args.get("depot_id"):
        query = query.filter_by(depot_id=request.args["depot_id"])
    if request.args.get("period"):
        query = query.filter_by(period=request.args["period"])
    return jsonify([performance_data(item) for item in query.all()])


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
