from app.extensions import db
from app.models import Depot, Sale, User, Vendor


def _login(client, email, password):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.get_json()["access_token"]}


def _seed_accounts():
    first = Depot(name="Depot A", location="Lome")
    second = Depot(name="Depot B", location="Kara")
    db.session.add_all([first, second])
    db.session.flush()
    depositaire = User(name="Depot A", email="depot@test.tg", role="depositaire", depot_id=first.id)
    depositaire.set_password("secret123")
    admin = User(name="Admin", email="admin@test.tg", role="administrateur")
    admin.set_password("secret123")
    vendor_a = Vendor(phone="22890000001", name="Afi", depot_id=first.id)
    vendor_b = Vendor(phone="22890000002", name="Kossi", depot_id=second.id)
    db.session.add_all([depositaire, admin, vendor_a, vendor_b])
    db.session.flush()
    sale_a = Sale(vendor_phone=vendor_a.phone, depot_id=first.id, period="Matin", amount=1000)
    sale_b = Sale(vendor_phone=vendor_b.phone, depot_id=second.id, period="Matin", amount=2000)
    db.session.add_all([sale_a, sale_b])
    db.session.commit()
    return sale_a.id, sale_b.id


def test_depositaire_is_scoped_to_its_depot(client):
    with client.application.app_context():
        own_id, other_id = _seed_accounts()
    headers = _login(client, "depot@test.tg", "secret123")
    response = client.get("/api/depositaire/sales", headers=headers)
    assert response.status_code == 200
    assert [item["id"] for item in response.get_json()] == [own_id]
    response = client.patch(
        "/api/depositaire/sales/{}".format(other_id),
        headers=headers,
        json={"action": "validate"},
    )
    assert response.status_code == 404


def test_rejection_requires_a_reason(client):
    with client.application.app_context():
        own_id, _ = _seed_accounts()
    headers = _login(client, "depot@test.tg", "secret123")
    response = client.patch(
        "/api/depositaire/sales/{}".format(own_id),
        headers=headers,
        json={"action": "reject", "reason": ""},
    )
    assert response.status_code == 400
    assert "motif" in response.get_json()["error"].lower()


def test_admin_cannot_validate_a_sale(client):
    with client.application.app_context():
        own_id, _ = _seed_accounts()
    headers = _login(client, "admin@test.tg", "secret123")
    response = client.patch(
        "/api/depositaire/sales/{}".format(own_id),
        headers=headers,
        json={"action": "validate"},
    )
    assert response.status_code == 403


def test_invalid_login_is_rejected(client):
    response = client.post("/api/auth/login", json={"email": "none@test.tg", "password": "bad"})
    assert response.status_code == 401


def test_user_can_update_own_profile(client):
    with client.application.app_context():
        _seed_accounts()
    headers = _login(client, "admin@test.tg", "secret123")
    response = client.patch("/api/me", headers=headers, json={
        "name": "Administratrice FanMilk",
        "email": "direction@fanmilk.tg",
        "phone": "+228 90 00 00 00",
        "password": "nouveau-secret",
    })
    assert response.status_code == 200
    assert response.get_json()["name"] == "Administratrice FanMilk"
    assert response.get_json()["email"] == "direction@fanmilk.tg"
    assert _login(client, "direction@fanmilk.tg", "nouveau-secret")


def test_profile_email_must_remain_unique(client):
    with client.application.app_context():
        _seed_accounts()
    headers = _login(client, "admin@test.tg", "secret123")
    response = client.patch(
        "/api/me",
        headers=headers,
        json={"email": "depot@test.tg"},
    )
    assert response.status_code == 409


def test_admin_can_create_a_vendor_account_with_phone(client):
    with client.application.app_context():
        _seed_accounts()
        depot_id = Depot.query.filter_by(name="Depot A").first().id
    headers = _login(client, "admin@test.tg", "secret123")
    response = client.post("/api/admin/users", headers=headers, json={
        "name": "Nouvelle vendeuse", "email": "vendeuse@test.tg", "password": "secret123",
        "role": "revendeur", "depot_id": depot_id, "phone": "22893334444",
    })
    assert response.status_code == 201
    with client.application.app_context():
        assert db.session.get(Vendor, "22893334444") is not None
