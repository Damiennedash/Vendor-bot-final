from datetime import date

from app.conversation import handle_message
from app.extensions import db
from app.models import BotSession, Depot, Sale, Vendor
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


def test_each_message_reloads_the_authoritative_database_session(client):
    phone = "22898889999"
    handle_message(phone, "Bonjour")

    session = db.session.get(BotSession, phone)
    session.step = "vente_aujourd_hui"
    session.data = {"nom": "Damienne", "depot": "YEHONAM"}
    db.session.commit()

    reply, _ = handle_message(phone, "2")
    assert "*aujourd hui* en FCFA" in reply
    db.session.expire_all()
    assert db.session.get(BotSession, phone).step == "ventes_montant"


def test_sales_and_difficulty_questions_stay_in_order(client):
    phone = "22893365551"
    expected = [
        ("Bonjour", "Veuillez entrer votre *nom*"),
        ("DAMIENNE", "Choisissez votre *depot*"),
        ("6", "Concernant vos ventes *aujourd hui*"),
        ("2", "aujourd hui* en FCFA"),
        ("45000", "Combien de *FanXtra*"),
        ("3", "Combien de *FanChoco*"),
        ("4", "Combien de *FanVanille*"),
        ("5", "Ou avez-vous vendu *aujourd hui*"),
        ("1", "probleme *au cours de la journee*"),
        ("1", "Probleme Produit"),
        ("Ety", "Votre declaration a bien ete enregistree"),
    ]

    for message, expected_text in expected:
        reply, completed_row = handle_message(phone, message)
        assert expected_text in reply

    assert completed_row is not None
    session = db.session.get(BotSession, phone)
    assert session.step == "start"
    assert session.data == {}
