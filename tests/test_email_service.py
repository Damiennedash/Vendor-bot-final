from app.email_service import email_is_configured, send_password_reset_email


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
