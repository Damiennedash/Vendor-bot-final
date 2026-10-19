from app.extensions import db
from app.models import Sale
from test_api import _seed_accounts, _login


def test_sale_review_does_not_wait_for_whatsapp(client, monkeypatch):
    pending = []
    monkeypatch.setattr('app.notifications.executor.submit', lambda fn: pending.append(fn))
    with client.application.app_context():
        own, other = _seed_accounts()
    headers = _login(client, 'depot@test.tg', 'secret123')
    response = client.patch(f'/api/depositaire/sales/{own}', headers=headers, json={'action': 'validate'})
    assert response.status_code == 200
    assert response.json['status'] == 'validee'
    assert len(pending) == 1
    with client.application.app_context():
        assert db.session.get(Sale, own).status == 'validee'
    sent = []
    monkeypatch.setattr('app.whatsapp.send_message', lambda *args: sent.append(args) or True)
    pending[0]()
    assert len(sent) == 1


def test_vendor_history_is_filtered_and_protected(client):
    with client.application.app_context():
        own, other = _seed_accounts()
        phone = db.session.get(Sale, own).vendor_phone
    headers = _login(client, 'admin@test.tg', 'secret123')
    response = client.get('/api/admin/sales', query_string={'vendor_phone': phone}, headers=headers)
    assert response.status_code == 200
    assert [row['id'] for row in response.json] == [own]
    assert client.get('/api/admin/sales', query_string={'vendor_phone': phone}).status_code == 401
