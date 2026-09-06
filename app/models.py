from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Depot(db.Model):
    __tablename__ = "depots"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    location = db.Column(db.String(255), nullable=False, default="Togo")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (db.CheckConstraint("role IN ('administrateur', 'depositaire', 'revendeur')", name="ck_user_role"),)
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(32), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False)
    depot_id = db.Column(db.Integer, db.ForeignKey("depots.id"), index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    depot = db.relationship("Depot")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    user = db.relationship("User")


class Vendor(db.Model):
    __tablename__ = "vendors"
    phone = db.Column(db.String(32), primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    depot_id = db.Column(db.Integer, db.ForeignKey("depots.id"), nullable=False, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    last_declaration_at = db.Column(db.DateTime)
    last_sales_amount = db.Column(db.BigInteger, nullable=False, default=0)
    last_fanxtra = db.Column(db.Integer, nullable=False, default=0)
    last_fanchoco = db.Column(db.Integer, nullable=False, default=0)
    last_fanvanille = db.Column(db.Integer, nullable=False, default=0)
    last_pieces = db.Column(db.Integer, nullable=False, default=0)
    last_sales_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    depot = db.relationship("Depot")


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(64), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)


class Sale(db.Model):
    __tablename__ = "sales"
    __table_args__ = (db.CheckConstraint("status IN ('en_attente', 'validee', 'rejetee')", name="ck_sale_status"),)
    id = db.Column(db.Integer, primary_key=True)
    vendor_phone = db.Column(db.String(32), db.ForeignKey("vendors.phone"), nullable=False, index=True)
    depot_id = db.Column(db.Integer, db.ForeignKey("depots.id"), nullable=False, index=True)
    declared_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
    period = db.Column(db.String(16), nullable=False)
    amount = db.Column(db.BigInteger, nullable=False, default=0)
    location = db.Column(db.String(255), nullable=False, default="")
    status = db.Column(db.String(24), nullable=False, default="en_attente", index=True)
    rejection_reason = db.Column(db.Text)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    source = db.Column(db.String(64), nullable=False, default="WhatsApp")
    vendor = db.relationship("Vendor")
    depot = db.relationship("Depot")
    lines = db.relationship("SaleLine", cascade="all, delete-orphan", lazy="selectin")


class SaleLine(db.Model):
    __tablename__ = "sale_lines"
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    subtotal = db.Column(db.BigInteger, nullable=False, default=0)
    product = db.relationship("Product")


class Stock(db.Model):
    __tablename__ = "stocks"
    __table_args__ = (db.CheckConstraint("status IN ('en_attente', 'valide', 'rejete')", name="ck_stock_status"),)
    id = db.Column(db.Integer, primary_key=True)
    vendor_phone = db.Column(db.String(32), db.ForeignKey("vendors.phone"), nullable=False, index=True)
    depot_id = db.Column(db.Integer, db.ForeignKey("depots.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    declared_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    status = db.Column(db.String(24), nullable=False, default="en_attente", index=True)
    rejection_reason = db.Column(db.Text)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    vendor = db.relationship("Vendor")
    depot = db.relationship("Depot")
    product = db.relationship("Product")


class Difficulty(db.Model):
    __tablename__ = "difficulties"
    __table_args__ = (db.CheckConstraint("state IN ('ouverte', 'en_cours', 'resolue')", name="ck_difficulty_state"),)
    id = db.Column(db.Integer, primary_key=True)
    vendor_phone = db.Column(db.String(32), db.ForeignKey("vendors.phone"), nullable=False, index=True)
    depot_id = db.Column(db.Integer, db.ForeignKey("depots.id"), nullable=False, index=True)
    category = db.Column(db.String(120), nullable=False)
    prime_pillar = db.Column(db.String(64), nullable=False, default="")
    description = db.Column(db.Text, nullable=False, default="")
    reported_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    state = db.Column(db.String(24), nullable=False, default="ouverte", index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    vendor = db.relationship("Vendor")
    depot = db.relationship("Depot")


class Performance(db.Model):
    __tablename__ = "performances"
    __table_args__ = (db.UniqueConstraint("vendor_phone", "period", name="uq_performance_vendor_period"),)
    id = db.Column(db.Integer, primary_key=True)
    vendor_phone = db.Column(db.String(32), db.ForeignKey("vendors.phone"), nullable=False, index=True)
    depot_id = db.Column(db.Integer, db.ForeignKey("depots.id"), nullable=False, index=True)
    period = db.Column(db.String(32), nullable=False)
    total_sales = db.Column(db.BigInteger, nullable=False, default=0)
    score = db.Column(db.Float, nullable=False, default=0)
    validated_sales = db.Column(db.Integer, nullable=False, default=0)
    rejected_sales = db.Column(db.Integer, nullable=False, default=0)
    vendor = db.relationship("Vendor")
    depot = db.relationship("Depot")


class Bonus(db.Model):
    __tablename__ = "bonuses"
    id = db.Column(db.Integer, primary_key=True)
    vendor_phone = db.Column(db.String(32), db.ForeignKey("vendors.phone"), nullable=False, index=True)
    depot_id = db.Column(db.Integer, db.ForeignKey("depots.id"), nullable=False, index=True)
    period = db.Column(db.String(32), nullable=False)
    amount = db.Column(db.BigInteger, nullable=False)
    awarded_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    awarded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    vendor = db.relationship("Vendor")
    depot = db.relationship("Depot")


class BotSession(db.Model):
    __tablename__ = "bot_sessions"
    phone = db.Column(db.String(32), primary_key=True)
    step = db.Column(db.String(64), nullable=False, default="start")
    data = db.Column(db.JSON, nullable=False, default=dict)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class ProcessedMessage(db.Model):
    __tablename__ = "processed_messages"
    message_id = db.Column(db.String(191), primary_key=True)
    processed_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
