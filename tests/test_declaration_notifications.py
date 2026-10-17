from unittest.mock import Mock

import pytest

from app.extensions import db
from app.models import Depot, Difficulty, Notification, User
from app.repository import append_declaration
from app import notifications


@pytest.fixture()
def recipients(client, monkeypatch):
    monkeypatch.setattr(notifications.executor, "submit", Mock())
    depot = Depot(name="YEHONAM")
    other = Depot(name="AUTRE")
    db.session.add_all([depot, other])
    db.session.flush()
    for email, role, depot_id, active in [
        ("depot@test.tg", "depositaire", depot.id, True),
        ("other@test.tg", "depositaire", other.id, True),
        ("admin@test.tg", "administrateur", None, True),
        ("inactive@test.tg", "administrateur", None, False),
    ]:
        db.session.add(User(name=email, email=email, role=role, depot_id=depot_id,
                            active=active, password_hash="unused"))
    db.session.commit()


def declaration(category="Aucun probleme", description="", hour="09:00"):
    return ["14/09/2026", hour, "Matin", "22891112222", "Afi", "YEHONAM",
            "J ai deja vendu", "20000", "2", "1", "0", "Marche", category,
            "Produit", description, "WhatsApp"]


@pytest.mark.parametrize("category", ["Aucun probleme", "Aucun problème", "-", ""])
def test_normal_declaration_emails_only_own_depot(recipients, monkeypatch, category):
    append_declaration(declaration(category))
    rows = Notification.query.all()
    assert [(n.recipient.email, n.kind) for n in rows] == [("depot@test.tg", "vente")]
    assert Difficulty.query.count() == 0
    sender = Mock(return_value=True)
    monkeypatch.setattr(notifications, "send_notification_email", sender)
    notifications._deliver(rows[0].id)
    assert sender.call_args.args[0] == "depot@test.tg"


def test_difficulty_emails_admin_and_declaration_emails_depot(recipients, monkeypatch):
    append_declaration(declaration("Produit", "Glaciere en panne"))
    rows = Notification.query.order_by(Notification.id).all()
    assert [(n.recipient.email, n.kind) for n in rows] == [
        ("depot@test.tg", "vente"), ("admin@test.tg", "difficulte")]
    assert "Glaciere en panne" in rows[1].message
    assert rows[1].link == "/dashboard/difficultes"
    sender = Mock(return_value=True)
    monkeypatch.setattr(notifications, "send_notification_email", sender)
    for row in rows:
        notifications._deliver(row.id)
    assert [call.args[0] for call in sender.call_args_list] == ["depot@test.tg", "admin@test.tg"]


def test_same_day_new_occurrence_is_preserved_and_notified(recipients):
    append_declaration(declaration("Produit", "Premiere panne"))
    append_declaration(declaration("Produit", "Nouvelle panne", "15:30"))
    assert [d.description for d in Difficulty.query.order_by(Difficulty.id)] == [
        "Premiere panne", "Nouvelle panne"]
    assert Notification.query.filter_by(kind="difficulte").count() == 2


def test_draft_does_not_notify_or_create_difficulty(recipients):
    row = declaration("Produit", "Panne")
    row[15] = "WhatsApp - saisie en cours"
    append_declaration(row)
    assert Notification.query.count() == 0
    assert Difficulty.query.count() == 0
    row[15] = "WhatsApp"
    append_declaration(row)
    assert Difficulty.query.count() == 1
    assert Notification.query.count() == 2


def test_difficulty_only_followup_preserves_sales_and_routes_notifications(recipients):
    from app.models import Sale

    append_declaration(declaration())
    row = declaration("Produit", "Panne supplementaire", "15:30")
    row[15] = "WhatsApp - suivi difficultes"
    append_declaration(row)
    assert Sale.query.count() == 1
    assert Sale.query.one().amount == 20000
    assert Difficulty.query.one().description == "Panne supplementaire"
    assert [(n.recipient.email, n.kind) for n in Notification.query.order_by(Notification.id)] == [
        ("depot@test.tg", "vente"),
        ("depot@test.tg", "information"),
        ("admin@test.tg", "difficulte"),
    ]
    row[12] = "Aucun probleme"
    row[14] = ""
    append_declaration(row)
    assert Sale.query.count() == 1
    assert Notification.query.filter_by(kind="difficulte").count() == 1
