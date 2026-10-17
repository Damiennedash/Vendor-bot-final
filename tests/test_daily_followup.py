from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from app import notifications
from app.conversation import handle_message
from app.extensions import db
from app.models import BotSession, Difficulty, Notification, Sale
from app.repository import append_declaration


@pytest.fixture(autouse=True)
def no_delivery(monkeypatch):
    monkeypatch.setattr(notifications.executor, "submit", Mock())


def complete_first(phone):
    for message in ("Bonjour", "Afi", "6", "2", "20000", "2", "1", "0", "2", "7"):
        _, row = handle_message(phone, message)
        if row:
            append_declaration(row)
    return Sale.query.filter_by(vendor_phone=phone).one()


@pytest.mark.parametrize("status", ["en_attente", "validee"])
def test_same_day_only_asks_difficulties_and_preserves_sales(client, status):
    phone = "22891112222"
    sale = complete_first(phone)
    sale.status = status
    db.session.commit()
    reply, row = handle_message(phone, "Bonjour")
    assert "encore rencontre des difficultes" in reply
    assert row is None
    handle_message(phone, "5")
    _, row = handle_message(phone, "Glaciere en panne")
    assert row[15] == "WhatsApp - suivi difficultes"
    append_declaration(row)
    db.session.refresh(sale)
    assert Sale.query.count() == 1
    assert sale.amount == 20000
    assert sale.status == status
    assert sum(line.quantity for line in sale.lines) == 3
    assert Difficulty.query.one().description == "Glaciere en panne"
    reply, _ = handle_message(phone, "menu")
    assert "encore rencontre des difficultes" in reply
    _, row = handle_message(phone, "7")
    append_declaration(row)
    assert Sale.query.count() == 1
    assert Difficulty.query.count() == 1


def test_rejected_declaration_requires_fresh_figures_even_for_option_one(client):
    phone = "22891112222"
    sale = complete_first(phone)
    sale.status = "rejetee"
    db.session.commit()
    reply, _ = handle_message(phone, "Bonjour")
    assert "Concernant vos ventes" in reply
    reply, _ = handle_message(phone, "1")
    assert "Combien avez-vous vendu" in reply
    for message in ("15000", "1", "1", "0", "2", "7"):
        _, row = handle_message(phone, message)
        if row:
            append_declaration(row)
    assert Sale.query.count() == 2
    assert sale.status == "rejetee"
    assert Sale.query.order_by(Sale.id.desc()).first().amount == 15000
    reply, _ = handle_message(phone, "Bonjour")
    assert "encore rencontre des difficultes" in reply


def test_next_day_reopens_sales_even_after_followup_started(client):
    phone = "22891112222"
    sale = complete_first(phone)
    handle_message(phone, "Bonjour")
    yesterday = datetime.now() - timedelta(days=1)
    sale.declared_at = yesterday
    session = db.session.get(BotSession, phone)
    session.data = {**session.data, "followup_date": yesterday.strftime("%d/%m/%Y")}
    db.session.commit()
    reply, _ = handle_message(phone, "Bonjour")
    assert "Concernant vos ventes" in reply


def test_incomplete_draft_does_not_count_as_submitted(client):
    phone = "22891112222"
    for message in ("Bonjour", "Afi", "6", "2", "20000", "2", "1", "0"):
        handle_message(phone, message)
    assert Sale.query.one().source == "WhatsApp - saisie en cours"
    reply, _ = handle_message(phone, "menu")
    assert "Concernant vos ventes" in reply
