from datetime import date, datetime, timedelta
from functools import wraps
import base64
import hashlib
import io
import logging
import os
import secrets

import pyotp
import qrcode
from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .email_service import email_is_configured, send_password_reset_email
from .audit import record_audit
from .models import BrowserSession, AuditLog, Bonus, Depot, Difficulty, MfaRecoveryCode, Notification, PasswordResetToken, Performance, Product, ProductTarget, Sale, SaleLine, Stock, User, Vendor, utc_now
from .notifications import retry_notification


from .permissions import (PRIMARY_ADMIN_EMAIL, PERMISSION_MODULES, EDITABLE, ALL_PERMISSIONS,
                          is_primary_admin, effective_permissions, has_permission, notification_visible)

# Explicit endpoint map: new administrator endpoints are denied until classified.
ADMIN_ENDPOINT_MODULES = {
    "admin_summary": "pilotage", "list_users": "comptes", "create_user": "comptes",
    "update_user": "comptes", "reset_user_mfa": "comptes", "list_vendors": "revendeurs",
    "admin_performances": "performances", "admin_bonuses": "performances",
    "admin_product_totals": "donnees", "admin_product_breakdown": "donnees",
    "difficulty_assignees": "difficultes", "admin_difficulties": "difficultes", "update_difficulty": "difficultes",
    "admin_sales": "donnees", "admin_stocks": "donnees", "admin_analytics": "analyses",
    "admin_targets": "analyses", "admin_audit": "audit", "admin_notifications": "notifications",
    "retry_admin_notification": "notifications", "system_status": "systeme",
}

api = Blueprint("api", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapped(*args, **kwargs):
            if get_jwt().get("scope") != "authenticated":
                return jsonify({"error": "Acces interdit"}), 403
            user = current_user()
            if not user or not user.active:
                return jsonify({"error": "Compte suspendu"}), 401
            if user.role not in roles:
                return jsonify({"error": "Acces interdit"}), 403
            if user.role == "administrateur" and request.path.startswith("/api/admin/"):
                if fn.__name__ in {"permission_catalog", "update_admin_permissions"}:
                    if not is_primary_admin(user):
                        return jsonify({"error": "Réservé à l’administratrice principale"}), 403
                elif fn.__name__ == "list_depots":
                    if not effective_permissions(user):
                        return jsonify({"error": "Accès non autorisé"}), 403
                else:
                    module = ADMIN_ENDPOINT_MODULES.get(fn.__name__)
                    action = "view" if request.method in {"GET", "HEAD"} else "edit"
                    if not module or not has_permission(user, f"{module}.{action}"):
                        return jsonify({"error": "Vous n’avez pas l’autorisation pour cette fonctionnalité"}), 403
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
        "mfa_enabled": user.mfa_enabled,
        "is_primary_admin": is_primary_admin(user),
        "permissions": effective_permissions(user),
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


def requested_depot_id():
    raw_value = request.args.get("depot_id")
    if raw_value in (None, ""):
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return -1


def apply_date_filters(query, column):
    """Applique des bornes inclusives AAAA-MM-JJ aux listes métier."""
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    try:
        if date_from:
            query = query.filter(column >= datetime.strptime(date_from, "%Y-%m-%d"))
        if date_to:
            query = query.filter(column < datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1))
    except ValueError:
        return None
    return query


def authenticated_token(user):
    return create_access_token(
        identity=str(user.id),
        additional_claims={
            "scope": "authenticated", "role": user.role, "depot_id": user.depot_id
        },
    )


def mfa_setup_payload(user):
    uri = pyotp.TOTP(user.mfa_secret).provisioning_uri(
        name=user.email, issuer_name="FanMilk Togo"
    )
    image = qrcode.make(uri)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return {
        "manual_key": user.mfa_secret,
        "provisioning_uri": uri,
        "qr_code": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii"),
    }


def notification_data(item):
    return {
        "id": item.id,
        "recipient": user_data(item.recipient),
        "kind": item.kind,
        "title": item.title,
        "message": item.message,
        "priority": item.priority,
        "link": item.link,
        "read": item.read_at is not None,
        "email_status": item.email_status,
        "whatsapp_status": item.whatsapp_status,
        "delivery_attempts": item.delivery_attempts,
        "last_delivery_error": item.last_delivery_error,
        "last_attempt_at": iso(item.last_attempt_at),
        "created_at": iso(item.created_at),
    }


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
                Sale.amount > 0,
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
    monthly_sales = Sale.query.filter(
        Sale.vendor_phone.in_(phones),
        Sale.status == "validee",
        Sale.amount > 0,
        Sale.declared_at >= start,
        Sale.declared_at < end,
    ).order_by(Sale.declared_at.desc(), Sale.id.desc()).all() if phones else []
    bonuses_by_sale = {
        bonus.sale_id: bonus
        for bonus in Bonus.query.filter(Bonus.sale_id.isnot(None)).all()
    }
    sales_by_vendor = {}
    for sale in monthly_sales:
        bonus = bonuses_by_sale.get(sale.id)
        sales_by_vendor.setdefault(sale.vendor_phone, []).append({
            "id": sale.id,
            "date": sale.declared_at.strftime("%Y-%m-%d"),
            "amount": sale.amount,
            "eligible": sale.amount > 18000,
            "bonus_awarded": bonus is not None,
            "bonus_amount": bonus.amount if bonus else 0,
        })
    for vendor in vendors:
        stats = aggregates.get(vendor.phone, {})
        validated = stats.get("validee", {"count": 0, "amount": 0})
        rejected = stats.get("rejetee", {"count": 0, "amount": 0})
        pending = stats.get("en_attente", {"count": 0, "amount": 0})
        processed_count = validated["count"] + rejected["count"]
        score = round(validated["count"] * 100 / processed_count) if processed_count else 0
        average = round(depot_totals.get(vendor.depot_id, 0) / max(depot_vendor_counts.get(vendor.depot_id, 1), 1))
        daily_sales = sales_by_vendor.get(vendor.phone, [])
        eligible = any(sale["eligible"] and not sale["bonus_awarded"] for sale in daily_sales)
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
            "suggested_bonus": 500 if eligible else 0,
            "daily_sales": daily_sales,
        })
    return result


def product_totals_rows(depot_id=None, period_value=None):
    query = db.session.query(
        Product.sku,
        Product.name,
        func.coalesce(func.sum(SaleLine.quantity), 0),
    ).join(SaleLine, SaleLine.product_id == Product.id).join(
        Sale, Sale.id == SaleLine.sale_id
    ).filter(Sale.status == "validee", Sale.amount > 0)
    if depot_id:
        query = query.filter(Sale.depot_id == depot_id)
    if period_value:
        bounds = month_bounds(period_value)
        if bounds is None:
            return None
        query = query.filter(Sale.declared_at >= bounds[0], Sale.declared_at < bounds[1])
    query = apply_date_filters(query, Sale.declared_at)
    if query is None:
        return None
    totals = {sku: {"sku": sku, "name": name, "quantity": int(quantity or 0)}
              for sku, name, quantity in query.group_by(Product.sku, Product.name).all()}
    names = {"FANXTRA": "FanXtra", "FANCHOCO": "FanChoco", "FANVANILLE": "FanVanille"}
    return [totals.get(sku, {"sku": sku, "name": name, "quantity": 0})
            for sku, name in names.items()]


def product_breakdown_rows(depot_id=None, period_value=None):
    query = db.session.query(
        Vendor.phone,
        Vendor.name,
        Depot.name,
        Product.sku,
        Product.name,
        func.coalesce(func.sum(SaleLine.quantity), 0),
    ).join(Sale, Sale.vendor_phone == Vendor.phone).join(
        SaleLine, SaleLine.sale_id == Sale.id
    ).join(Product, Product.id == SaleLine.product_id).join(
        Depot, Depot.id == Sale.depot_id
    ).filter(Sale.status == "validee", Sale.amount > 0)
    if depot_id:
        query = query.filter(Sale.depot_id == depot_id)
    if period_value:
        bounds = month_bounds(period_value)
        if bounds is None:
            return None
        query = query.filter(Sale.declared_at >= bounds[0], Sale.declared_at < bounds[1])
    query = apply_date_filters(query, Sale.declared_at)
    if query is None:
        return None
    rows = query.group_by(
        Vendor.phone, Vendor.name, Depot.name, Product.sku, Product.name
    ).order_by(Vendor.name, Product.sku).all()
    return [{
        "vendor": {"phone": phone, "name": vendor_name},
        "depot": depot_name,
        "sku": sku,
        "product": product_name,
        "quantity": int(quantity or 0),
    } for phone, vendor_name, depot_name, sku, product_name, quantity in rows]


def sale_data(sale):
    return {
        "id": sale.id,
        "vendor": vendor_data(sale.vendor),
        "depot": {"id": sale.depot.id, "name": sale.depot.name},
        "declared_at": iso(sale.declared_at),
        "sales_date": (sale.sales_date or sale.declared_at.date()).isoformat(),
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


def sale_stock_data(sale):
    """One stock declaration per sale; sale review is the only source of status."""
    data = sale_data(sale)
    data.update({
        "sale_id": sale.id,
        "product": {"sku": " / ".join(line["sku"] for line in data["lines"]),
                    "name": " · ".join(f'{line["product"]} × {line["quantity"]}' for line in data["lines"])},
        "quantity": sum(line["quantity"] for line in data["lines"]),
        "status": {"validee": "valide", "rejetee": "rejete"}.get(sale.status, sale.status),
    })
    return data


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
        "action_plan": item.action_plan,
        "assigned_admin": {"id": item.assigned_admin.id, "name": item.assigned_admin.name} if item.assigned_admin else None,
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
        "sale_id": item.sale_id,
    }


@api.post("/auth/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    # Les adresses sont normalisées en minuscules à la création. Une comparaison
    # directe permet à PostgreSQL d'utiliser l'index unique au lieu de parcourir
    # toute la table avec LOWER(email) à chaque connexion.
    user = User.query.filter_by(email=email).first()
    if not user:
        # Compatibilité avec d'anciens comptes saisis avant la normalisation.
        user = User.query.filter(func.lower(User.email) == email).first()
    if not user or not user.active or not user.check_password(str(payload.get("password", ""))):
        return jsonify({"error": "Identifiants invalides"}), 401
    if user.role == "revendeur":
        return jsonify({
            "error": "Les revendeurs utilisent Vendor-Bot sur WhatsApp pour leurs déclarations."
        }), 403
    if not user.mfa_secret:
        user.mfa_secret = pyotp.random_base32()
        db.session.commit()
    challenge = create_access_token(
        identity=str(user.id),
        additional_claims={"scope": "mfa_pending"},
        expires_delta=timedelta(minutes=5),
    )
    return jsonify({
        "mfa_required": True,
        "mfa_setup_required": not user.mfa_enabled,
        "mfa_token": challenge,
        **(mfa_setup_payload(user) if not user.mfa_enabled else {}),
    })


@api.post("/auth/mfa/verify")
@jwt_required()
def verify_mfa():
    if get_jwt().get("scope") != "mfa_pending":
        return jsonify({"error": "Session de vérification invalide"}), 403
    user = current_user()
    code = str((request.get_json(silent=True) or {}).get("code", "")).replace(" ", "")
    if not user or not user.active or not user.mfa_secret:
        return jsonify({"error": "Compte indisponible"}), 401
    first_setup = not user.mfa_enabled
    valid_totp = pyotp.TOTP(user.mfa_secret).verify(code, valid_window=1)
    recovery = None
    if not valid_totp and user.mfa_enabled:
        recovery = MfaRecoveryCode.query.filter_by(
            user_id=user.id,
            code_hash=hashlib.sha256(code.upper().encode("utf-8")).hexdigest(),
            used_at=None,
        ).first()
    if not valid_totp and not recovery:
        return jsonify({"error": "Code Google Authenticator ou code de secours invalide"}), 401
    if recovery:
        recovery.used_at = utc_now()
    recovery_codes = []
    if first_setup:
        MfaRecoveryCode.query.filter_by(user_id=user.id).delete()
        recovery_codes = [secrets.token_hex(4).upper() for _ in range(8)]
        for raw_code in recovery_codes:
            db.session.add(MfaRecoveryCode(
                user_id=user.id,
                code_hash=hashlib.sha256(raw_code.encode("utf-8")).hexdigest(),
            ))
    user.mfa_enabled = True
    db.session.commit()
    response = jsonify({
        "access_token": authenticated_token(user),
        "user": user_data(user),
        **({"recovery_codes": recovery_codes} if recovery_codes else {}),
    })
    raw = secrets.token_urlsafe(48)
    db.session.add(BrowserSession(token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        user_id=user.id, credential_hash=session_credentials(user),
        expires_at=utc_now() + timedelta(days=30)))
    db.session.commit()
    response.set_cookie("fanmilk_session", raw, max_age=30 * 86400,
        secure=True, httponly=True, samesite="Strict", path="/api/auth")
    return response



@api.post("/auth/forgot-password")
def forgot_password():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    message = "Si ce compte existe, le lien de réinitialisation vient d'être envoyé. Vérifiez aussi vos spams."

    if not email_is_configured():
        return jsonify({
            "error": "L'envoi d'e-mail n'est pas encore configuré. Contactez l'administrateur FanMilk."
        }), 503

    user = User.query.filter(func.lower(User.email) == email, User.active.is_(True)).first()

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

    # Le lien doit toujours revenir vers le site public utilisé par les équipes.
    # On n'utilise plus l'ancienne URL Sites privée, même si une variable Render
    # historique est encore présente.
    frontend_url = "https://fanmilk-togo.damiennedash.workers.dev"
    reset_url = "{}/reinitialisation?token={}".format(frontend_url, raw_token)
    try:
        send_password_reset_email(user.email, user.name, reset_url)
    except Exception:
        logger.exception("Échec de l'envoi de récupération pour l'utilisateur %s", user.id)
        reset_token.used_at = utc_now()
        db.session.commit()
        return jsonify({
            "error": "L'e-mail n'a pas pu être envoyé. Réessayez dans quelques minutes."
        }), 503

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
    if get_jwt().get("scope") != "authenticated":
        return jsonify({"error": "Double authentification requise"}), 403
    user = current_user()
    if not user or not user.active:
        return jsonify({"error": "Compte inactif"}), 401
    return jsonify({
        **user_data(user),
        "depot": {"id": user.depot.id, "name": user.depot.name, "location": user.depot.location} if user.depot else None,
        "mfa_enabled": user.mfa_enabled,
    })


@api.patch("/me")
@jwt_required()
def update_me():
    if get_jwt().get("scope") != "authenticated":
        return jsonify({"error": "Double authentification requise"}), 403
    user = current_user()
    if not user or not user.active:
        return jsonify({"error": "Compte inactif"}), 401

    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", user.name)).strip()
    email = str(payload.get("email", user.email)).strip().lower()
    phone = str(payload.get("phone", user.phone or "")).strip() or None
    password = str(payload.get("password", ""))

    if email != user.email.strip().lower() and (is_primary_admin(user) or email == PRIMARY_ADMIN_EMAIL):
        return jsonify({"error": "L’adresse du compte principal est protégée"}), 403
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


@api.get("/notifications")
@jwt_required()
def list_notifications():
    if get_jwt().get("scope") != "authenticated":
        return jsonify({"error": "Double authentification requise"}), 403
    if not current_user() or not current_user().active:
        return jsonify({"error": "Compte inactif"}), 401
    rows = Notification.query.filter_by(recipient_user_id=current_user().id).order_by(
        Notification.created_at.desc()
    ).limit(50).all()
    return jsonify([notification_data(item) for item in rows if notification_visible(current_user(), item)])


@api.patch("/notifications/<int:item_id>")
@jwt_required()
def read_notification(item_id):
    if get_jwt().get("scope") != "authenticated":
        return jsonify({"error": "Double authentification requise"}), 403
    item = Notification.query.filter_by(
        id=item_id, recipient_user_id=current_user().id
    ).first_or_404()
    if not notification_visible(current_user(), item):
        return jsonify({"error": "Accès interdit"}), 403
    item.read_at = utc_now()
    db.session.commit()
    return jsonify({"id": item.id, "read": True})


@api.get("/depositaire/summary")
@role_required("depositaire")
def depositaire_summary():
    depot_id = current_user().depot_id
    pending_sales = Sale.query.filter_by(depot_id=depot_id, status="en_attente").count()
    pending_stocks = pending_sales
    today_sales = db.session.scalar(db.select(func.coalesce(func.sum(Sale.amount), 0)).where(
        Sale.depot_id == depot_id, Sale.status == "validee", func.date(Sale.declared_at) == date.today()
    ))
    active_vendors = Vendor.query.filter_by(depot_id=depot_id, active=True).count()
    return jsonify({"pending_sales": pending_sales, "pending_stocks": pending_stocks, "today_revenue": today_sales, "active_vendors": active_vendors})


@api.get("/depositaire/sales")
@role_required("depositaire")
def depositaire_sales():
    query = Sale.query.options(joinedload(Sale.vendor), joinedload(Sale.depot), selectinload(Sale.lines).joinedload(SaleLine.product)).filter_by(depot_id=current_user().depot_id)
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    query = apply_date_filters(query, Sale.declared_at)
    if query is None:
        return jsonify({"error": "Dates invalides"}), 400
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
    before = {"status": sale.status, "rejection_reason": sale.rejection_reason}
    sale.status = "validee" if action == "validate" else "rejetee"
    sale.rejection_reason = reason or None
    sale.reviewed_at = utc_now()
    sale.reviewed_by = user.id
    record_audit(user, "validation" if action == "validate" else "rejet", "vente", sale.id,
                 "Vente {} par {}".format(sale.id, sale.vendor.name), before,
                 {"status": sale.status, "rejection_reason": sale.rejection_reason})
    db.session.commit()
    if action == "reject":
        from .repository import latest_daily_declaration, save_bot_session
        latest = latest_daily_declaration(sale.vendor_phone)
        if latest and latest.id == sale.id:
            save_bot_session(sale.vendor_phone, {"step": "start", "data": {}})
    message = "Votre vente a ete validee." if action == "validate" else (
        "Votre vente a ete rejetee. Motif : " + reason
        + "\nEnvoyez Bonjour pour reprendre votre declaration depuis le debut."
    )
    from .notifications import queue_sale_message
    queue_sale_message(sale.vendor_phone, message)
    return jsonify(sale_data(sale))


@api.get("/depositaire/stocks")
@role_required("depositaire")
def depositaire_stocks():
    query = Sale.query.options(joinedload(Sale.vendor), joinedload(Sale.depot), selectinload(Sale.lines).joinedload(SaleLine.product)).filter_by(depot_id=current_user().depot_id)
    status = request.args.get("status")
    if status:
        query = query.filter_by(status={"valide": "validee", "rejete": "rejetee"}.get(status, status))
    query = apply_date_filters(query, Sale.declared_at)
    if query is None:
        return jsonify({"error": "Dates invalides"}), 400
    return jsonify([sale_stock_data(item) for item in query.order_by(Sale.declared_at.desc()).all()])


@api.get("/depositaire/product-totals")
@role_required("depositaire")
def depositaire_product_totals():
    rows = product_totals_rows(
        depot_id=current_user().depot_id, period_value=request.args.get("period")
    )
    if rows is None:
        return jsonify({"error": "Période invalide"}), 400
    return jsonify(rows)


@api.get("/depositaire/product-breakdown")
@role_required("depositaire")
def depositaire_product_breakdown():
    rows = product_breakdown_rows(
        depot_id=current_user().depot_id, period_value=request.args.get("period")
    )
    if rows is None:
        return jsonify({"error": "Période invalide"}), 400
    return jsonify(rows)


@api.patch("/depositaire/stocks/<int:stock_id>")
@role_required("depositaire")
def review_stock(stock_id):
    Sale.query.filter_by(id=stock_id, depot_id=current_user().depot_id).first_or_404()
    return jsonify({"error": "Validez ou rejetez la vente associée dans la rubrique Ventes. Son stock suit automatiquement la même décision."}), 409


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
    rows = Bonus.query.filter_by(depot_id=current_user().depot_id).filter(
        Bonus.sale_id.isnot(None)
    ).order_by(Bonus.awarded_at.desc()).all()
    return jsonify([bonus_data(item) for item in rows])


@api.get("/depositaire/difficulties")
@role_required("depositaire")
def depositaire_difficulties():
    query = apply_date_filters(
        Difficulty.query.filter_by(depot_id=current_user().depot_id),
        Difficulty.reported_at,
    )
    if query is None:
        return jsonify({"error": "Dates invalides"}), 400
    rows = query.order_by(Difficulty.reported_at.desc()).all()
    return jsonify([difficulty_data(item) for item in rows])


@api.get("/depositaire/history")
@role_required("depositaire")
def depositaire_history():
    depot_id = current_user().depot_id
    sales = Sale.query.filter(Sale.depot_id == depot_id, Sale.status != "en_attente").order_by(Sale.declared_at.desc()).all()
    return jsonify({"sales": [sale_data(item) for item in sales], "stocks": [sale_stock_data(item) for item in sales]})


@api.get("/admin/summary")
@role_required("administrateur")
def admin_summary():
    bounds = month_bounds(request.args.get("period"))
    if bounds is None:
        return jsonify({"error": "Periode invalide, format attendu AAAA-MM"}), 400
    start, end = bounds
    depot_id = requested_depot_id()
    if depot_id == -1:
        return jsonify({"error": "Dépôt invalide"}), 400
    revenue_query = db.select(func.coalesce(func.sum(Sale.amount), 0)).where(
        Sale.status == "validee", Sale.declared_at >= start, Sale.declared_at < end
    )
    vendors_query = Vendor.query.filter_by(active=True)
    difficulties_query = Difficulty.query.filter(
        Difficulty.state != "resolue", Difficulty.reported_at >= start, Difficulty.reported_at < end
    )
    bonuses_query = db.select(func.coalesce(func.sum(Bonus.amount), 0)).where(
        Bonus.sale_id.isnot(None), Bonus.awarded_at >= start, Bonus.awarded_at < end
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
    depot_id = requested_depot_id()
    if depot_id == -1:
        return jsonify({"error": "Dépôt invalide"}), 400
    if depot_id:
        query = query.filter_by(depot_id=depot_id)
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
    if role == "administrateur" and not is_primary_admin(current_user()):
        return jsonify({"error": "Seul le compte principal peut créer un administrateur"}), 403
    if str(payload.get("email", "")).strip().lower() == PRIMARY_ADMIN_EMAIL:
        return jsonify({"error": "Cette adresse est réservée au compte principal"}), 403
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
        phone=phone,
        role=role,
        admin_permissions=[] if role == "administrateur" else None,
        depot_id=depot_id,
    )
    user.set_password(payload["password"])
    db.session.add(user)
    db.session.flush()
    record_audit(current_user(), "creation", "utilisateur", user.id,
                 "Création du compte {}".format(user.name), None, user_data(user))
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

    if (user.role == "administrateur" or role == "administrateur") and not is_primary_admin(current_user()):
        return jsonify({"error": "Seul le compte principal peut modifier un administrateur"}), 403
    if is_primary_admin(user) and (email != PRIMARY_ADMIN_EMAIL or role != "administrateur" or not active):
        return jsonify({"error": "Le compte principal doit conserver son identité et son accès"}), 403
    if not is_primary_admin(user) and email == PRIMARY_ADMIN_EMAIL:
        return jsonify({"error": "Cette adresse est réservée au compte principal"}), 403
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

    before = user_data(user)
    user.name = name
    user.email = email
    if user.role != "administrateur" and role == "administrateur":
        user.admin_permissions = []
    user.role = role
    user.depot_id = None if role == "administrateur" else depot_id
    user.phone = phone
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
    record_audit(current_user(), "suspension" if before["active"] and not active else "modification",
                 "utilisateur", user.id, "Mise à jour du compte {}".format(user.name),
                 before, user_data(user))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Cette adresse ou ce numero existe deja"}), 409
    return jsonify(user_data(user))


@api.get("/admin/performances")
@role_required("administrateur")
def admin_performances():
    depot_id = requested_depot_id()
    if depot_id == -1:
        return jsonify({"error": "Dépôt invalide"}), 400
    rows = computed_performance_rows(
        depot_id=depot_id,
        period_value=request.args.get("period"),
    )
    if rows is None:
        return jsonify({"error": "Periode invalide, format attendu AAAA-MM"}), 400
    return jsonify(rows)


@api.get("/admin/product-totals")
@role_required("administrateur")
def admin_product_totals():
    depot_id = requested_depot_id()
    if depot_id == -1:
        return jsonify({"error": "Dépôt invalide"}), 400
    rows = product_totals_rows(depot_id=depot_id, period_value=request.args.get("period"))
    if rows is None:
        return jsonify({"error": "Periode invalide, format attendu AAAA-MM"}), 400
    return jsonify(rows)


@api.get("/admin/product-breakdown")
@role_required("administrateur")
def admin_product_breakdown():
    depot_id = requested_depot_id()
    if depot_id == -1:
        return jsonify({"error": "Dépôt invalide"}), 400
    rows = product_breakdown_rows(depot_id=depot_id, period_value=request.args.get("period"))
    if rows is None:
        return jsonify({"error": "Période invalide"}), 400
    return jsonify(rows)


@api.route("/admin/bonuses", methods=["GET", "POST"])
@role_required("administrateur")
def admin_bonuses():
    if request.method == "GET":
        depot_id = requested_depot_id()
        if depot_id == -1:
            return jsonify({"error": "Dépôt invalide"}), 400
        query = Bonus.query.filter(Bonus.sale_id.isnot(None))
        if depot_id:
            query = query.filter_by(depot_id=depot_id)
        period = request.args.get("period")
        if period:
            bounds = month_bounds(period)
            if bounds is None:
                return jsonify({"error": "Periode invalide, format attendu AAAA-MM"}), 400
            query = query.join(Sale, Sale.id == Bonus.sale_id).filter(
                Sale.declared_at >= bounds[0], Sale.declared_at < bounds[1]
            )
        return jsonify([bonus_data(item) for item in query.order_by(Bonus.awarded_at.desc()).all()])
    payload = request.get_json(silent=True) or {}
    sale = db.session.get(Sale, payload.get("sale_id"))
    if not sale or sale.status != "validee":
        return jsonify({"error": "Vente validée introuvable"}), 400
    if sale.amount <= 18000:
        return jsonify({"error": "La vente doit dépasser 18 000 FCFA"}), 400
    if Bonus.query.filter_by(sale_id=sale.id).first():
        return jsonify({"error": "La prime de cette vente a déjà été attribuée"}), 409
    item = Bonus(
        vendor_phone=sale.vendor_phone,
        depot_id=sale.depot_id,
        period=sale.declared_at.strftime("%Y-%m-%d"),
        amount=500,
        awarded_by=current_user().id,
        sale_id=sale.id,
    )
    db.session.add(item)
    db.session.flush()
    record_audit(current_user(), "attribution", "prime", item.id,
                 "Prime de 500 FCFA attribuée à {} pour la vente {}".format(sale.vendor.name, sale.id),
                 None, {"sale_id": sale.id, "amount": 500, "vendor": sale.vendor.name})
    db.session.commit()
    from .notifications import notify_users, recipients_for_depot
    notify_users(
        recipients_for_depot(sale.depot_id, include_admin=False, depositaires_only=True),
        "prime",
        "Prime attribuée à {}".format(sale.vendor.name),
        "Une prime de 500 FCFA a été attribuée pour la vente du {} ({} FCFA).".format(
            item.period, sale.amount
        ),
        "/depositaire/primes",
    )
    return jsonify(bonus_data(item)), 201


@api.get("/admin/difficulties")
@role_required("administrateur")
def admin_difficulties():
    query = Difficulty.query.options(joinedload(Difficulty.vendor), joinedload(Difficulty.depot), joinedload(Difficulty.assigned_admin))
    depot_id = requested_depot_id()
    if depot_id == -1:
        return jsonify({"error": "Dépôt invalide"}), 400
    if depot_id:
        query = query.filter_by(depot_id=depot_id)
    query = apply_date_filters(query, Difficulty.reported_at)
    if query is None:
        return jsonify({"error": "Dates invalides"}), 400
    return jsonify([difficulty_data(item) for item in query.order_by(Difficulty.reported_at.desc()).all()])


@api.patch("/admin/difficulties/<int:item_id>")
@role_required("administrateur")
def update_difficulty(item_id):
    item = Difficulty.query.filter_by(id=item_id).first_or_404()
    payload = request.get_json(silent=True) or {}
    state = payload.get("state", item.state)
    allowed = {"ouverte": "en_cours", "en_cours": "resolue"}
    if state != item.state and allowed.get(item.state) != state:
        return jsonify({"error": "Transition d'état invalide"}), 400
    plan = payload.get("action_plan", item.action_plan)
    if not isinstance(plan, str) or len(plan) > 5000:
        return jsonify({"error": "Les actions doivent contenir au maximum 5000 caractères."}), 400
    assignee_id = payload.get("assigned_admin_id", item.assigned_admin_id)
    assignee = None
    if assignee_id is not None:
        if type(assignee_id) is not int:
            return jsonify({"error": "Administrateur invalide"}), 400
        assignee = db.session.get(User, assignee_id)
        if not assignee or not assignee.active or not has_permission(assignee, "difficultes.view"):
            return jsonify({"error": "Choisissez un administrateur actif autorisé à consulter les difficultés."}), 400
    before = {"state": item.state, "action_plan": item.action_plan, "assigned_admin_id": item.assigned_admin_id}
    changed_assignee = assignee_id != item.assigned_admin_id
    item.state, item.action_plan, item.assigned_admin_id = state, plan.strip(), assignee_id
    if changed_assignee and assignee:
        db.session.add(Notification(recipient_user_id=assignee.id, kind="difficulte",
            title="Une difficulté vous a été attribuée",
            message=f"{current_user().name} vous confie le suivi de {item.vendor.name} : {item.category}. Actions : {item.action_plan or 'À définir'}",
            link=f"/dashboard/difficultes#difficulty-{item.id}",
            email_status="ignore", whatsapp_status="ignore"))
    record_audit(current_user(), "suivi_difficulte", "difficulte", item.id,
        f"Suivi de la difficulté {item.id}", before,
        {"state": state, "action_plan": item.action_plan, "assigned_admin_id": assignee_id})
    db.session.commit()
    return jsonify(difficulty_data(item))


@api.get("/admin/difficulty-assignees")
@role_required("administrateur")
def difficulty_assignees():
    users = User.query.filter_by(role="administrateur", active=True).order_by(User.name).all()
    return jsonify([{"id": user.id, "name": user.name} for user in users if has_permission(user, "difficultes.view")])


@api.get("/admin/sales")
@role_required("administrateur")
def admin_sales():
    query = Sale.query.options(joinedload(Sale.vendor), joinedload(Sale.depot), selectinload(Sale.lines).joinedload(SaleLine.product))
    vendor_phone = request.args.get("vendor_phone")
    if vendor_phone:
        query = query.filter_by(vendor_phone=vendor_phone)
    depot_id = requested_depot_id()
    if depot_id == -1:
        return jsonify({"error": "Dépôt invalide"}), 400
    if depot_id:
        query = query.filter_by(depot_id=depot_id)
    query = apply_date_filters(query, Sale.declared_at)
    if query is None:
        return jsonify({"error": "Dates invalides"}), 400
    return jsonify([sale_data(item) for item in query.order_by(Sale.declared_at.desc()).all()])


@api.get("/admin/stocks")
@role_required("administrateur")
def admin_stocks():
    query = Sale.query.options(joinedload(Sale.vendor), joinedload(Sale.depot), selectinload(Sale.lines).joinedload(SaleLine.product))
    depot_id = requested_depot_id()
    if depot_id == -1:
        return jsonify({"error": "Dépôt invalide"}), 400
    if depot_id:
        query = query.filter_by(depot_id=depot_id)
    query = apply_date_filters(query, Sale.declared_at)
    if query is None:
        return jsonify({"error": "Dates invalides"}), 400
    return jsonify([sale_stock_data(item) for item in query.order_by(Sale.declared_at.desc()).all()])


@api.get("/admin/depots")
@role_required("administrateur")
def list_depots():
    return jsonify([{"id": item.id, "name": item.name, "location": item.location} for item in Depot.query.order_by(Depot.name).all()])


@api.post("/admin/users/<int:user_id>/reset-mfa")
@role_required("administrateur")
def reset_user_mfa(user_id):
    actor = current_user()
    user = db.session.get(User, user_id) or User.query.filter_by(id=user_id).first_or_404()
    if user.role == "administrateur" and not is_primary_admin(actor):
        return jsonify({"error": "Seul le compte principal peut réinitialiser un administrateur"}), 403
    before = {"mfa_enabled": user.mfa_enabled}
    user.mfa_secret = None
    user.mfa_enabled = False
    MfaRecoveryCode.query.filter_by(user_id=user.id).delete()
    record_audit(actor, "reinitialisation_mfa", "utilisateur", user.id,
                 "Réinitialisation MFA du compte {}".format(user.name), before,
                 {"mfa_enabled": False})
    db.session.commit()
    return jsonify({"message": "La double authentification sera reconfigurée à la prochaine connexion."})


@api.get("/admin/system-status")
@role_required("administrateur")
def system_status():
    return jsonify({
        "email_configured": email_is_configured(),
        "whatsapp_configured": bool(os.getenv("WHATSAPP_TOKEN", "").strip()),
        "frontend_url": os.getenv("FRONTEND_URL", "").strip(),
        "database": "connectee",
    })


@api.get("/admin/notifications")
@role_required("administrateur")
def admin_notifications():
    limit = min(max(request.args.get("limit", 100, type=int), 1), 500)
    rows = Notification.query.order_by(Notification.created_at.desc()).limit(limit).all()
    return jsonify([notification_data(item) for item in rows])


@api.post("/admin/notifications/<int:item_id>/retry")
@role_required("administrateur")
def retry_admin_notification(item_id):
    item = db.session.get(Notification, item_id) or Notification.query.filter_by(id=item_id).first_or_404()
    retry_notification(item.id)
    item = db.session.get(Notification, item.id)
    record_audit(current_user(), "nouvelle_tentative", "notification", item.id,
                 "Nouvelle tentative de livraison de la notification {}".format(item.id),
                 None, {"email_status": item.email_status, "whatsapp_status": item.whatsapp_status})
    db.session.commit()
    return jsonify(notification_data(item))


@api.get("/admin/audit")
@role_required("administrateur")
def admin_audit():
    query = apply_date_filters(AuditLog.query, AuditLog.created_at)
    if query is None:
        return jsonify({"error": "Dates invalides"}), 400
    rows = query.order_by(AuditLog.created_at.desc()).limit(500).all()
    return jsonify([{
        "id": item.id,
        "actor": user_data(item.actor) if item.actor else None,
        "action": item.action,
        "entity_type": item.entity_type,
        "entity_id": item.entity_id,
        "description": item.description,
        "before": item.before_data,
        "after": item.after_data,
        "created_at": iso(item.created_at),
    } for item in rows])


def _target_rows(period, depot_id):
    bounds = month_bounds(period)
    if bounds is None:
        return None
    start, end = bounds
    actual_query = (
        db.session.query(SaleLine.product_id, func.coalesce(func.sum(SaleLine.quantity), 0))
        .join(Sale, Sale.id == SaleLine.sale_id)
        .filter(Sale.status == "validee", Sale.declared_at >= start, Sale.declared_at < end)
    )
    if depot_id:
        actual_query = actual_query.filter(Sale.depot_id == depot_id)
    actual = {product_id: int(quantity or 0) for product_id, quantity in actual_query.group_by(SaleLine.product_id).all()}
    targets_query = ProductTarget.query.filter_by(period=period)
    targets_query = targets_query.filter(ProductTarget.depot_id == depot_id) if depot_id else targets_query.filter(ProductTarget.depot_id.is_(None))
    targets = {item.product_id: item for item in targets_query.all()}
    return [{
        "id": targets.get(product.id).id if targets.get(product.id) else None,
        "product": {"id": product.id, "sku": product.sku, "name": product.name},
        "depot_id": depot_id,
        "period": period,
        "quantity_target": targets.get(product.id).quantity_target if targets.get(product.id) else 0,
        "actual_quantity": actual.get(product.id, 0),
        "completion_rate": round(actual.get(product.id, 0) * 100 / targets.get(product.id).quantity_target, 1) if targets.get(product.id) and targets.get(product.id).quantity_target else 0,
    } for product in Product.query.filter_by(active=True).order_by(Product.name).all()]


@api.route("/admin/targets", methods=["GET", "PUT"])
@role_required("administrateur")
def admin_targets():
    if request.method == "GET":
        period = request.args.get("period") or date.today().strftime("%Y-%m")
        depot_id = requested_depot_id()
        if depot_id == -1:
            return jsonify({"error": "Dépôt invalide"}), 400
        rows = _target_rows(period, depot_id)
        return jsonify(rows) if rows is not None else (jsonify({"error": "Période invalide"}), 400)
    payload = request.get_json(silent=True) or {}
    period = str(payload.get("period", ""))
    depot_id = payload.get("depot_id") or None
    product = db.session.get(Product, payload.get("product_id"))
    if month_bounds(period) is None or not product:
        return jsonify({"error": "Produit ou période invalide"}), 400
    try:
        quantity = int(payload.get("quantity_target", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Objectif invalide"}), 400
    if quantity < 0:
        return jsonify({"error": "L'objectif ne peut pas être négatif"}), 400
    query = ProductTarget.query.filter_by(product_id=product.id, period=period)
    query = query.filter(ProductTarget.depot_id == depot_id) if depot_id else query.filter(ProductTarget.depot_id.is_(None))
    item = query.first()
    before = {"quantity_target": item.quantity_target} if item else None
    if not item:
        item = ProductTarget(product_id=product.id, depot_id=depot_id, period=period,
                             updated_by=current_user().id)
        db.session.add(item)
    item.quantity_target = quantity
    item.updated_by = current_user().id
    db.session.flush()
    record_audit(current_user(), "objectif_produit", "objectif", item.id,
                 "Objectif {} fixé à {} unités".format(product.name, quantity), before,
                 {"quantity_target": quantity, "period": period, "depot_id": depot_id})
    db.session.commit()
    return jsonify(_target_rows(period, depot_id))


@api.get("/admin/analytics")
@role_required("administrateur")
def admin_analytics():
    period = request.args.get("period") or date.today().strftime("%Y-%m")
    bounds = month_bounds(period)
    depot_id = requested_depot_id()
    if bounds is None or depot_id == -1:
        return jsonify({"error": "Période ou dépôt invalide"}), 400
    start, end = bounds
    previous_end = start
    previous_start = datetime(start.year - 1, 12, 1) if start.month == 1 else datetime(start.year, start.month - 1, 1)

    def scoped_sales(start_at, end_at):
        query = Sale.query.filter(Sale.status == "validee", Sale.declared_at >= start_at, Sale.declared_at < end_at)
        return query.filter(Sale.depot_id == depot_id) if depot_id else query

    current_query = scoped_sales(start, end)
    previous_query = scoped_sales(previous_start, previous_end)
    current_revenue = int(db.session.scalar(db.select(func.coalesce(func.sum(Sale.amount), 0)).where(Sale.id.in_(current_query.with_entities(Sale.id)))) or 0)
    previous_revenue = int(db.session.scalar(db.select(func.coalesce(func.sum(Sale.amount), 0)).where(Sale.id.in_(previous_query.with_entities(Sale.id)))) or 0)
    daily_rows = current_query.with_entities(func.date(Sale.declared_at), func.sum(Sale.amount), func.count(Sale.id)).group_by(func.date(Sale.declared_at)).order_by(func.date(Sale.declared_at)).all()
    vendor_query = current_query.join(Vendor, Vendor.phone == Sale.vendor_phone).join(Depot, Depot.id == Sale.depot_id).with_entities(
        Vendor.phone, Vendor.name, Depot.name, func.sum(Sale.amount), func.count(Sale.id)
    ).group_by(Vendor.phone, Vendor.name, Depot.name).order_by(func.sum(Sale.amount).desc())
    depot_query = current_query.join(Depot, Depot.id == Sale.depot_id).with_entities(
        Depot.id, Depot.name, func.sum(Sale.amount), func.count(Sale.id)
    ).group_by(Depot.id, Depot.name).order_by(func.sum(Sale.amount).desc())
    delta = round((current_revenue - previous_revenue) * 100 / previous_revenue, 1) if previous_revenue else (100 if current_revenue else 0)
    return jsonify({
        "period": period,
        "current_revenue": current_revenue,
        "previous_revenue": previous_revenue,
        "change_percent": delta,
        "validated_sales": current_query.count(),
        "pending_sales": (Sale.query.filter_by(status="en_attente", **({"depot_id": depot_id} if depot_id else {})).count()),
        "daily": [{"date": str(day), "amount": int(amount or 0), "sales": int(count)} for day, amount, count in daily_rows],
        "vendor_ranking": [{"phone": phone, "name": name, "depot": depot, "amount": int(amount or 0), "sales": int(count)} for phone, name, depot, amount, count in vendor_query.limit(50).all()],
        "depot_ranking": [{"id": row_id, "name": name, "amount": int(amount or 0), "sales": int(count)} for row_id, name, amount, count in depot_query.all()],
        "product_targets": _target_rows(period, depot_id),
    })


@api.get("/admin/permissions")
@role_required("administrateur")
def permission_catalog():
    return jsonify([{"key": key, "label": label, "editable": key in EDITABLE}
                    for key, label in PERMISSION_MODULES.items()])


@api.put("/admin/users/<int:user_id>/permissions")
@role_required("administrateur")
def update_admin_permissions(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "Compte introuvable"}), 404
    if user.role != "administrateur" or is_primary_admin(user):
        return jsonify({"error": "Les droits du compte principal ne peuvent pas être restreints"}), 400
    permissions = (request.get_json(silent=True) or {}).get("permissions")
    if not isinstance(permissions, list) or any(not isinstance(p, str) or p not in ALL_PERMISSIONS for p in permissions):
        return jsonify({"error": "Liste de permissions invalide"}), 400
    normalized = set(permissions)
    for permission in permissions:
        if permission.endswith(".edit"):
            normalized.add(permission.removesuffix(".edit") + ".view")
    if any(p.split(".")[0] in {"audit", "notifications", "systeme"} for p in normalized):
        normalized.add("analyses.view")
    before = user_data(user)
    user.admin_permissions = sorted(normalized)
    record_audit(current_user(), "permissions", "utilisateur", user.id,
                 "Modification des droits de {}".format(user.name), before, user_data(user))
    db.session.commit()
    return jsonify(user_data(user))


def session_credentials(user):
    return hashlib.sha256((user.password_hash + "|" + (user.mfa_secret or "")).encode()).hexdigest()


@api.post("/auth/session")
def restore_browser_session():
    # A custom header prevents cross-site form submissions; CORS only permits trusted sites.
    if request.headers.get("X-FanMilk-Session") != "1":
        return jsonify({"error": "Requête non autorisée"}), 403
    raw = request.cookies.get("fanmilk_session", "")
    saved = BrowserSession.query.filter_by(token_hash=hashlib.sha256(raw.encode()).hexdigest()).first() if raw else None
    if (not saved or saved.expires_at <= utc_now() or not saved.user.active
        or not saved.user.mfa_enabled or saved.user.role not in {"administrateur", "depositaire"}
        or saved.credential_hash != session_credentials(saved.user)):
        response = jsonify({"error": "Session expirée. Veuillez vous reconnecter."})
        response.status_code = 401
        response.delete_cookie("fanmilk_session", path="/api/auth", secure=True, httponly=True, samesite="Strict")
        return response
    return jsonify({"access_token": authenticated_token(saved.user), "user": user_data(saved.user)})


@api.post("/auth/logout")
def logout_browser_session():
    if request.headers.get("X-FanMilk-Session") != "1":
        return jsonify({"error": "Requête non autorisée"}), 403
    raw = request.cookies.get("fanmilk_session", "")
    if raw:
        BrowserSession.query.filter_by(token_hash=hashlib.sha256(raw.encode()).hexdigest()).delete()
        db.session.commit()
    response = jsonify({"ok": True})
    response.delete_cookie("fanmilk_session", path="/api/auth", secure=True, httponly=True, samesite="Strict")
    return response
