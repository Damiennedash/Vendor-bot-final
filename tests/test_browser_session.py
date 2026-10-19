from app.extensions import db
from app.models import User, BrowserSession
from test_api import _seed_accounts, _login

HEADERS = {'X-FanMilk-Session': '1'}

def test_restore_requires_mfa_and_logout_revokes(client):
    with client.application.app_context():
        _seed_accounts()
    assert client.post('/api/auth/session', headers=HEADERS).status_code == 401
    client.post('/api/auth/login', json={'email':'admin@test.tg','password':'secret123'})
    assert client.post('/api/auth/session', headers=HEADERS).status_code == 401
    _login(client, 'admin@test.tg', 'secret123')
    assert client.post('/api/auth/session').status_code == 403
    restored = client.post('/api/auth/session', headers=HEADERS)
    assert restored.status_code == 200
    assert restored.json['user']['email'] == 'admin@test.tg'
    assert client.post('/api/auth/logout', headers=HEADERS).status_code == 200
    assert client.post('/api/auth/session', headers=HEADERS).status_code == 401
    with client.application.app_context():
        assert BrowserSession.query.count() == 0


def test_password_change_invalidates_persistent_session(client):
    with client.application.app_context():
        _seed_accounts()
    _login(client, 'admin@test.tg', 'secret123')
    with client.application.app_context():
        User.query.filter_by(email='admin@test.tg').first().set_password('changed-password')
        db.session.commit()
    assert client.post('/api/auth/session', headers=HEADERS).status_code == 401


def test_suspended_and_expired_sessions_are_rejected(client):
    with client.application.app_context():
        _seed_accounts()
    _login(client, 'admin@test.tg', 'secret123')
    with client.application.app_context():
        user = User.query.filter_by(email='admin@test.tg').first()
        user.active = False
        db.session.commit()
    assert client.post('/api/auth/session', headers=HEADERS).status_code == 401


def test_cookie_is_secure_and_http_only(client):
    import pyotp
    with client.application.app_context():
        _seed_accounts()
    challenge = client.post('/api/auth/login', json={'email':'admin@test.tg','password':'secret123'}).json['mfa_token']
    with client.application.app_context():
        secret = User.query.filter_by(email='admin@test.tg').first().mfa_secret
    result = client.post('/api/auth/mfa/verify', headers={'Authorization':'Bearer '+challenge}, json={'code':pyotp.TOTP(secret).now()})
    cookie = result.headers['Set-Cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=Strict' in cookie
    assert 'Max-Age=2592000' in cookie


def test_expired_session_is_rejected(client):
    from datetime import timedelta
    from app.models import utc_now
    with client.application.app_context():
        _seed_accounts()
    _login(client, 'admin@test.tg', 'secret123')
    with client.application.app_context():
        BrowserSession.query.first().expires_at = utc_now() - timedelta(seconds=1)
        db.session.commit()
    assert client.post('/api/auth/session', headers=HEADERS).status_code == 401
