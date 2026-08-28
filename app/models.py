from datetime import datetime, timezone

from .extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Vendor(db.Model):
    __tablename__ = "vendors"

    phone = db.Column(db.String(32), primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    depot = db.Column(db.String(120), nullable=False)
    last_declaration_at = db.Column(db.DateTime)
    last_sales_amount = db.Column(db.BigInteger, nullable=False, default=0)
    last_fanxtra = db.Column(db.Integer, nullable=False, default=0)
    last_fanchoco = db.Column(db.Integer, nullable=False, default=0)
    last_fanvanille = db.Column(db.Integer, nullable=False, default=0)
    last_pieces = db.Column(db.Integer, nullable=False, default=0)
    last_sales_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )


class Declaration(db.Model):
    __tablename__ = "declarations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    declared_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
    period = db.Column(db.String(16), nullable=False)
    vendor_phone = db.Column(
        db.String(32), db.ForeignKey("vendors.phone"), nullable=False, index=True
    )
    vendor_name = db.Column(db.String(120), nullable=False)
    depot = db.Column(db.String(120), nullable=False, index=True)
    sales_status = db.Column(db.String(64), nullable=False)
    sales_amount = db.Column(db.BigInteger, nullable=False, default=0)
    fanxtra = db.Column(db.Integer, nullable=False, default=0)
    fanchoco = db.Column(db.Integer, nullable=False, default=0)
    fanvanille = db.Column(db.Integer, nullable=False, default=0)
    sales_locations = db.Column(db.Text, nullable=False, default="")
    issue_category = db.Column(db.String(120), nullable=False, default="")
    prime_pillar = db.Column(db.String(64), nullable=False, default="")
    comment = db.Column(db.Text, nullable=False, default="")
    source = db.Column(db.String(64), nullable=False, default="WhatsApp QR")


class BotSession(db.Model):
    __tablename__ = "bot_sessions"

    phone = db.Column(db.String(32), primary_key=True)
    step = db.Column(db.String(64), nullable=False, default="start")
    data = db.Column(db.JSON, nullable=False, default=dict)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )


class ProcessedMessage(db.Model):
    __tablename__ = "processed_messages"

    message_id = db.Column(db.String(191), primary_key=True)
    processed_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
