from app.extensions import db
from datetime import datetime
import pyotp

from app.models import AuditLog, Depot, MfaRecoveryCode, PasswordResetToken, Product, ProductTarget, Sale, SaleLine, User, Vendor


def _login(client, email, password):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    challenge = response.get_json()["mfa_token"]
    with client.application.app_context():
        secret = User.query.filter_by(email=email).first().mfa_secret
    verified = client.post(
        "/api/auth/mfa/verify",
        headers={"Authorization": "Bearer " + challenge},
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert verified.status_code == 200
    return {"Authorization": "Bearer " + verified.get_json()["access_token"]}


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


def test_login_requires_google_authenticator_code(client):
    with client.application.app_context():
        _seed_accounts()
    response = client.post(
        "/api/auth/login", json={"email": "admin@test.tg", "password": "secret123"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["mfa_required"] is True
    assert body["mfa_setup_required"] is True
    assert body["qr_code"].startswith("data:image/png;base64,")
    refused = client.post(
        "/api/auth/mfa/verify",
        headers={"Authorization": "Bearer " + body["mfa_token"]},
        json={"code": "000000"},
    )
    assert refused.status_code == 401


def test_mfa_setup_returns_one_time_recovery_codes(client):
    with client.application.app_context():
        _seed_accounts()
    response = client.post(
        "/api/auth/login", json={"email": "admin@test.tg", "password": "secret123"}
    ).get_json()
    with client.application.app_context():
        secret = User.query.filter_by(email="admin@test.tg").one().mfa_secret
    verified = client.post(
        "/api/auth/mfa/verify",
        headers={"Authorization": "Bearer " + response["mfa_token"]},
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert verified.status_code == 200
    assert len(verified.get_json()["recovery_codes"]) == 8
    with client.application.app_context():
        assert MfaRecoveryCode.query.count() == 8


def test_admin_analytics_targets_and_audit(client):
    with client.application.app_context():
        sale_id, _ = _seed_accounts()
        sale = db.session.get(Sale, sale_id)
        sale.status = "validee"
        sale.amount = 25000
        sale.declared_at = datetime(2026, 9, 8, 12, 0)
        product = Product(sku="FANXTRA", name="FanXtra")
        db.session.add(product)
        db.session.flush()
        product_id = product.id
        db.session.add(SaleLine(sale_id=sale.id, product_id=product.id, quantity=4, subtotal=25000))
        depot_id = sale.depot_id
        db.session.commit()
    headers = _login(client, "admin@test.tg", "secret123")
    response = client.get("/api/admin/analytics?period=2026-09&depot_id={}".format(depot_id), headers=headers)
    assert response.status_code == 200
    assert response.get_json()["current_revenue"] == 25000
    target = client.put("/api/admin/targets", headers=headers, json={
        "product_id": product_id, "depot_id": depot_id, "period": "2026-09", "quantity_target": 10,
    })
    assert target.status_code == 200
    assert target.get_json()[0]["actual_quantity"] == 4
    with client.application.app_context():
        assert ProductTarget.query.count() == 1
        assert AuditLog.query.filter_by(action="objectif_produit").count() == 1


def test_password_reset_sends_one_time_link(client, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    with client.application.app_context():
        _seed_accounts()
    sent = {}

    def capture_email(recipient, recipient_name, reset_url):
        sent.update(recipient=recipient, name=recipient_name, url=reset_url)

    monkeypatch.setattr("app.api.send_password_reset_email", capture_email)
    response = client.post(
        "/api/auth/forgot-password", json={"email": "admin@test.tg"}
    )
    assert response.status_code == 200
    assert sent["recipient"] == "admin@test.tg"
    raw_token = sent["url"].split("token=", 1)[1]

    response = client.post(
        "/api/auth/reset-password",
        json={"token": raw_token, "password": "nouveau-secret"},
    )
    assert response.status_code == 200
    assert _login(client, "admin@test.tg", "nouveau-secret")

    reused = client.post(
        "/api/auth/reset-password",
        json={"token": raw_token, "password": "encore-secret"},
    )
    assert reused.status_code == 400


def test_password_reset_keeps_unknown_email_private(client, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.api.send_password_reset_email",
        lambda *args: pytest.fail("Aucun e-mail ne doit être envoyé"),
    )
    response = client.post(
        "/api/auth/forgot-password", json={"email": "absent@test.tg"}
    )
    assert response.status_code == 200
    with client.application.app_context():
        assert PasswordResetToken.query.count() == 0


def test_password_reset_reports_missing_email_configuration(client, monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    response = client.post(
        "/api/auth/forgot-password", json={"email": "admin@test.tg"}
    )
    assert response.status_code == 503
    assert "configuré" in response.get_json()["error"]


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


def test_depository_account_keeps_whatsapp_phone_for_alerts(client):
    with client.application.app_context():
        _seed_accounts()
        depot_id = Depot.query.filter_by(name="Depot A").first().id
    headers = _login(client, "admin@test.tg", "secret123")
    response = client.post("/api/admin/users", headers=headers, json={
        "name": "Nouvelle depositaire", "email": "nouvelle-depot@test.tg",
        "password": "secret123", "role": "depositaire", "depot_id": depot_id,
        "phone": "22894445555",
    })
    assert response.status_code == 201
    with client.application.app_context():
        user = User.query.filter_by(email="nouvelle-depot@test.tg").one()
        assert user.phone == "22894445555"


def test_admin_cannot_reuse_a_vendor_phone(client):
    with client.application.app_context():
        _seed_accounts()
        depot_id = Depot.query.filter_by(name="Depot A").first().id
    headers = _login(client, "admin@test.tg", "secret123")
    payload = {
        "name": "Vendeuse une", "email": "vendeuse1@test.tg", "password": "secret123",
        "role": "revendeur", "depot_id": depot_id, "phone": "22895556666",
    }
    assert client.post("/api/admin/users", headers=headers, json=payload).status_code == 201
    payload.update({"name": "Vendeuse deux", "email": "vendeuse2@test.tg"})
    response = client.post("/api/admin/users", headers=headers, json=payload)
    assert response.status_code == 409
    assert "telephone" in response.get_json()["error"]


def test_admin_can_list_every_vendor_including_whatsapp_only_profiles(client):
    with client.application.app_context():
        _seed_accounts()
    headers = _login(client, "admin@test.tg", "secret123")
    response = client.get("/api/admin/vendors", headers=headers)
    assert response.status_code == 200
    rows = response.get_json()
    assert {row["phone"] for row in rows} == {"22890000001", "22890000002"}
    assert all("sales_count" in row for row in rows)


def test_admin_can_edit_and_suspend_a_vendor_account(client):
    with client.application.app_context():
        _seed_accounts()
        depot = Depot.query.filter_by(name="Depot A").one()
        user = User(
            name="Ancien nom",
            email="vendeur-edit@test.tg",
            phone="22897770000",
            role="revendeur",
            depot_id=depot.id,
        )
        user.set_password("secret123")
        db.session.add_all([
            user,
            Vendor(phone=user.phone, name=user.name, depot_id=depot.id),
        ])
        db.session.commit()
        user_id = user.id
        depot_id = depot.id
    headers = _login(client, "admin@test.tg", "secret123")
    response = client.patch(
        f"/api/admin/users/{user_id}",
        headers=headers,
        json={
            "name": "Nouveau nom",
            "email": "vendeur-nouveau@test.tg",
            "role": "revendeur",
            "depot_id": depot_id,
            "phone": "22897770000",
            "active": False,
        },
    )
    assert response.status_code == 200
    assert response.get_json()["active"] is False
    with client.application.app_context():
        vendor = db.session.get(Vendor, "22897770000")
        assert vendor.name == "Nouveau nom"
        assert vendor.active is False


def test_performances_are_computed_from_sales_for_the_selected_month(client):
    with client.application.app_context():
        _seed_accounts()
        vendor_a = db.session.get(Vendor, "22890000001")
        vendor_b = db.session.get(Vendor, "22890000002")
        Sale.query.delete()
        db.session.add_all([
            Sale(
                vendor_phone=vendor_a.phone,
                depot_id=vendor_a.depot_id,
                period="Matin",
                amount=10000,
                status="validee",
                declared_at=datetime(2026, 9, 2, 9, 0),
            ),
            Sale(
                vendor_phone=vendor_a.phone,
                depot_id=vendor_a.depot_id,
                period="Matin",
                amount=5000,
                status="rejetee",
                declared_at=datetime(2026, 9, 3, 9, 0),
            ),
            Sale(
                vendor_phone=vendor_b.phone,
                depot_id=vendor_b.depot_id,
                period="Matin",
                amount=99999,
                status="validee",
                declared_at=datetime(2026, 8, 3, 9, 0),
            ),
        ])
        db.session.commit()
    headers = _login(client, "admin@test.tg", "secret123")
    response = client.get("/api/admin/performances?period=2026-09", headers=headers)
    assert response.status_code == 200
    rows = {row["vendor"]["phone"]: row for row in response.get_json()}
    assert rows["22890000001"]["total_sales"] == 10000
    assert rows["22890000001"]["validated_sales"] == 1
    assert rows["22890000001"]["rejected_sales"] == 1
    assert rows["22890000001"]["score"] == 50
    assert rows["22890000002"]["total_sales"] == 0


def test_depositaire_performances_are_computed_for_its_depot_only(client):
    with client.application.app_context():
        _seed_accounts()
        own_vendor = db.session.get(Vendor, "22890000001")
        other_vendor = db.session.get(Vendor, "22890000002")
        Sale.query.delete()
        db.session.add_all([
            Sale(
                vendor_phone=own_vendor.phone,
                depot_id=own_vendor.depot_id,
                period="Matin",
                amount=25000,
                status="validee",
                declared_at=datetime(2026, 9, 2, 9, 0),
            ),
            Sale(
                vendor_phone=other_vendor.phone,
                depot_id=other_vendor.depot_id,
                period="Matin",
                amount=99000,
                status="validee",
                declared_at=datetime(2026, 9, 2, 9, 0),
            ),
        ])
        db.session.commit()
    headers = _login(client, "depot@test.tg", "secret123")
    response = client.get(
        "/api/depositaire/performances?period=2026-09", headers=headers
    )
    assert response.status_code == 200
    rows = response.get_json()
    assert [row["vendor"]["phone"] for row in rows] == ["22890000001"]
    assert rows[0]["total_sales"] == 25000


def test_bonus_is_fixed_per_eligible_sale_and_zero_sales_are_not_counted(client, monkeypatch):
    with client.application.app_context():
        _seed_accounts()
        vendor = db.session.get(Vendor, "22890000001")
        Sale.query.delete()
        sales = [
            Sale(vendor_phone=vendor.phone, depot_id=vendor.depot_id, period="Matin", amount=0,
                 status="validee", declared_at=datetime(2026, 9, 1, 9, 0)),
            Sale(vendor_phone=vendor.phone, depot_id=vendor.depot_id, period="Matin", amount=18000,
                 status="validee", declared_at=datetime(2026, 9, 2, 9, 0)),
            Sale(vendor_phone=vendor.phone, depot_id=vendor.depot_id, period="Matin", amount=18001,
                 status="validee", declared_at=datetime(2026, 9, 3, 9, 0)),
        ]
        db.session.add_all(sales)
        db.session.commit()
        ineligible_id, eligible_id = sales[1].id, sales[2].id

    headers = _login(client, "admin@test.tg", "secret123")
    response = client.get("/api/admin/performances?period=2026-09", headers=headers)
    row = next(item for item in response.get_json() if item["vendor"]["phone"] == "22890000001")
    assert row["validated_sales"] == 2
    assert len(row["daily_sales"]) == 2
    assert row["suggested_bonus"] == 500

    monkeypatch.setattr("app.whatsapp.send_message", lambda *args: True)
    refused = client.post("/api/admin/bonuses", headers=headers, json={"sale_id": ineligible_id})
    assert refused.status_code == 400
    awarded = client.post("/api/admin/bonuses", headers=headers, json={"sale_id": eligible_id})
    assert awarded.status_code == 201
    assert awarded.get_json()["amount"] == 500
    assert awarded.get_json()["sale_id"] == eligible_id
    duplicate = client.post("/api/admin/bonuses", headers=headers, json={"sale_id": eligible_id})
    assert duplicate.status_code == 409


def test_product_totals_sum_only_validated_sales(client):
    with client.application.app_context():
        _seed_accounts()
        vendor = db.session.get(Vendor, "22890000001")
        product = Product(sku="FANXTRA", name="FanXtra")
        db.session.add(product)
        db.session.flush()
        valid = Sale(vendor_phone=vendor.phone, depot_id=vendor.depot_id, period="Matin",
                     amount=20000, status="validee", declared_at=datetime(2026, 9, 2, 9, 0))
        pending = Sale(vendor_phone=vendor.phone, depot_id=vendor.depot_id, period="Matin",
                       amount=30000, status="en_attente", declared_at=datetime(2026, 9, 3, 9, 0))
        db.session.add_all([valid, pending])
        db.session.flush()
        db.session.add_all([
            SaleLine(sale_id=valid.id, product_id=product.id, quantity=7, subtotal=20000),
            SaleLine(sale_id=pending.id, product_id=product.id, quantity=99, subtotal=30000),
        ])
        db.session.commit()
    headers = _login(client, "admin@test.tg", "secret123")
    response = client.get("/api/admin/product-totals?period=2026-09", headers=headers)
    assert response.status_code == 200
    totals = {item["sku"]: item["quantity"] for item in response.get_json()}
    assert totals == {"FANXTRA": 7, "FANCHOCO": 0, "FANVANILLE": 0}


def test_all_admin_depot_filters_accept_an_empty_depot(client):
    with client.application.app_context():
        _seed_accounts()
        empty = Depot(name="Depot vide", location="Lome")
        db.session.add(empty)
        db.session.commit()
        depot_id = empty.id
    headers = _login(client, "admin@test.tg", "secret123")
    paths = [
        f"/api/admin/summary?depot_id={depot_id}&period=2026-09",
        f"/api/admin/performances?depot_id={depot_id}&period=2026-09",
        f"/api/admin/product-totals?depot_id={depot_id}&period=2026-09",
        f"/api/admin/vendors?depot_id={depot_id}",
        f"/api/admin/difficulties?depot_id={depot_id}",
        f"/api/admin/sales?depot_id={depot_id}",
        f"/api/admin/stocks?depot_id={depot_id}",
    ]
    assert [client.get(path, headers=headers).status_code for path in paths] == [200] * len(paths)
