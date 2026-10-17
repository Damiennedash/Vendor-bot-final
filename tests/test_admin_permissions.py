from unittest.mock import Mock
from flask_jwt_extended import create_access_token
from app.extensions import db
from app.models import User, AuditLog, Notification
from app.permissions import PRIMARY_ADMIN_EMAIL, ALL_PERMISSIONS
from app import notifications


def account(email, permissions=None):
    user = User(name=email, email=email, role="administrateur", admin_permissions=permissions)
    user.set_password("test-password")
    db.session.add(user)
    db.session.commit()
    return user


def auth(user):
    return {"Authorization": "Bearer " + create_access_token(identity=str(user.id), additional_claims={"scope": "authenticated", "role": user.role})}


def test_owner_controls_permissions_and_revocation_is_immediate(client):
    owner = account(PRIMARY_ADMIN_EMAIL)
    third = account("third@example.com", [])
    owner_headers, third_headers = auth(owner), auth(third)
    assert client.get("/api/admin/difficulties", headers=third_headers).status_code == 403
    response = client.put(f"/api/admin/users/{third.id}/permissions", headers=owner_headers, json={"permissions": ["difficultes.edit"]})
    assert response.status_code == 200
    assert set(response.json["permissions"]) == {"difficultes.view", "difficultes.edit"}
    assert client.get("/api/admin/difficulties", headers=third_headers).status_code == 200
    assert client.get("/api/admin/sales", headers=third_headers).status_code == 403
    assert client.get("/api/admin/audit", headers=third_headers).status_code == 403
    assert client.get("/api/me", headers=third_headers).json["permissions"] == response.json["permissions"]
    assert client.put(f"/api/admin/users/{third.id}/permissions", headers=owner_headers, json={"permissions": []}).status_code == 200
    assert client.get("/api/admin/difficulties", headers=third_headers).status_code == 403
    assert AuditLog.query.filter_by(action="permissions").count() == 2


def test_view_does_not_allow_changes(client):
    third = account("third@example.com", ["difficultes.view"])
    headers = auth(third)
    assert client.get("/api/admin/difficulties", headers=headers).status_code == 200
    assert client.patch("/api/admin/difficulties/1", headers=headers, json={"state": "resolue"}).status_code == 403


def test_cannot_take_over_or_demote_primary_admin(client):
    owner = account(PRIMARY_ADMIN_EMAIL)
    third = account("third@example.com", ALL_PERMISSIONS)
    headers = auth(third)
    assert client.put(f"/api/admin/users/{third.id}/permissions", headers=headers, json={"permissions": ALL_PERMISSIONS}).status_code == 403
    assert client.patch(f"/api/admin/users/{owner.id}", headers=headers, json={"password": "take-over"}).status_code == 403
    assert client.post(f"/api/admin/users/{owner.id}/reset-mfa", headers=headers).status_code == 403
    assert client.patch("/api/me", headers=headers, json={"email": PRIMARY_ADMIN_EMAIL.upper()}).status_code == 403
    assert client.patch(f"/api/admin/users/{owner.id}", headers=auth(owner), json={"active": False}).status_code == 403
    assert client.put(f"/api/admin/users/{owner.id}/permissions", headers=auth(owner), json={"permissions": []}).status_code == 400
    assert client.post("/api/admin/users", headers=headers, json={"role": "administrateur"}).status_code == 403


def test_new_admin_has_no_access_until_owner_assigns_it(client):
    owner = account(PRIMARY_ADMIN_EMAIL)
    headers = auth(owner)
    response = client.post("/api/admin/users", headers=headers, json={"role": "administrateur", "name": "Third", "email": "new@example.com", "password": "test-password"})
    assert response.status_code == 201
    third = db.session.get(User, response.json["id"])
    assert third.admin_permissions == []
    assert client.get("/api/admin/summary", headers=auth(third)).status_code == 403
    assert client.put(f"/api/admin/users/{third.id}/permissions", headers=headers, json={"permissions": ["unknown"]}).status_code == 400


def test_removed_difficulty_permission_hides_alerts_and_prevents_delivery(client, monkeypatch):
    third = account("third@example.com", [])
    old = Notification(recipient_user_id=third.id, kind="difficulte", title="Private", message="Private")
    db.session.add(old); db.session.commit()
    assert client.get("/api/notifications", headers=auth(third)).json == []
    submit = Mock()
    monkeypatch.setattr(notifications.executor, "submit", submit)
    notifications.notify_users([third], "difficulte", "Private", "Private")
    submit.assert_not_called()
    send = Mock()
    monkeypatch.setattr(notifications, "send_notification_email", send)
    notifications.retry_notification(old.id)
    send.assert_not_called()


def test_changed_role_invalidates_old_privileges(client):
    third = account("third@example.com", ALL_PERMISSIONS)
    headers = auth(third)
    third.role = "revendeur"
    db.session.commit()
    assert client.get("/api/admin/sales", headers=headers).status_code == 403
