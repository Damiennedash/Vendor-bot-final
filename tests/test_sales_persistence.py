from datetime import date

from app.conversation import handle_message
from app.extensions import db
from app.models import Depot, Sale, Vendor
from app.repository import append_declaration, recover_missing_sales


def test_sale_is_visible_as_soon_as_product_figures_are_complete(client):
    phone = "22896667777"
    for message in ("Bonjour", "Damienne", "6", "2", "45000", "2", "1", "1"):
        handle_message(phone, message)

    sale = Sale.query.filter_by(vendor_phone=phone).one()
    assert sale.status == "en_attente"
    assert sale.depot.name == "YEHONAM"
    assert sale.vendor.name == "Damienne"
    assert sale.amount == 45000
    assert sale.source == "WhatsApp - saisie en cours"
    assert sum(line.quantity for line in sale.lines) == 4

    handle_message(phone, "2")
    _, completed_row = handle_message(phone, "7")
    append_declaration(completed_row)

    assert Sale.query.filter_by(vendor_phone=phone).count() == 1
    db.session.refresh(sale)
    assert sale.location == "Marche"
    assert sale.source == "WhatsApp"


def test_recovery_recreates_a_missing_pending_sale(client):
    depot = Depot(name="YEHONAM", location="Lome, Togo")
    vendor = Vendor(
        phone="22897778888",
        name="Damienne",
        depot=depot,
        last_sales_date=date(2026, 8, 30),
        last_sales_amount=30000,
        last_fanxtra=2,
        last_fanchoco=1,
        last_fanvanille=1,
        last_pieces=4,
    )
    db.session.add_all([depot, vendor])
    db.session.commit()

    assert recover_missing_sales() == 1
    sale = Sale.query.filter_by(vendor_phone=vendor.phone).one()
    assert sale.depot.name == "YEHONAM"
    assert sale.status == "en_attente"
    assert sale.amount == 30000
    assert sale.location == "A preciser"
    assert recover_missing_sales() == 0
