import os

import pytest

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["META_APP_SECRET"] = "test-meta-secret"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-verify-token"

from app.extensions import db
from app.main import app


@pytest.fixture()
def client():
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()
