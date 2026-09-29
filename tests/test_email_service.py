from app.email_service import email_is_configured, send_password_reset_email


def test_email_is_configured_with_brevo(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "brevo-key")
    monkeypatch.setenv("BREVO_SENDER_EMAIL", "fanmilk@gmail.com")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("FANMILK_EMAIL_API_KEY", raising=False)

    assert email_is_configured() is True


def test_password_reset_prefers_brevo_https(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            calls.append(("checked",))

    def fake_post(url, headers, json, timeout):
        calls.append(("post", url, headers, json, timeout))
        return FakeResponse()

    monkeypatch.setenv("BREVO_API_KEY", "brevo-key")
    monkeypatch.setenv("BREVO_SENDER_EMAIL", "fanmilk@gmail.com")
    monkeypatch.setenv("BREVO_SENDER_NAME", "FanMilk Togo")
    monkeypatch.setenv("SMTP_USERNAME", "smtp@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "unused-password")
    monkeypatch.setattr("app.email_service.requests.post", fake_post)

    send_password_reset_email(
        "admin@example.com", "Admin", "https://example.com/reset?token=secret"
    )

    request = next(call for call in calls if call[0] == "post")
    assert request[1] == "https://api.brevo.com/v3/smtp/email"
    assert request[2]["api-key"] == "brevo-key"
    assert request[3]["sender"] == {
        "name": "FanMilk Togo",
        "email": "fanmilk@gmail.com",
    }
    assert request[3]["to"] == [{"email": "admin@example.com"}]
    assert request[4] == 15
    assert ("checked",) in calls


def test_email_is_configured_with_smtp(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("FANMILK_EMAIL_API_KEY", raising=False)
    monkeypatch.setenv("SMTP_USERNAME", "fanmilk@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")

    assert email_is_configured() is True


def test_password_reset_uses_gmail_smtp(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            calls.append(("ehlo",))

        def starttls(self):
            calls.append(("starttls",))

        def login(self, username, password):
            calls.append(("login", username, password))

        def send_message(self, message):
            calls.append(("send", message["From"], message["To"], message["Subject"]))

    monkeypatch.setenv("SMTP_USERNAME", "fanmilk@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setattr("app.email_service.smtplib.SMTP", FakeSMTP)

    send_password_reset_email(
        "admin@example.com", "Admin", "https://example.com/reset?token=secret"
    )

    assert ("connect", "smtp.gmail.com", 587, 15) in calls
    assert ("starttls",) in calls
    assert ("login", "fanmilk@gmail.com", "abcdefghijklmnop") in calls
    assert any(call[0] == "send" and call[2] == "admin@example.com" for call in calls)
