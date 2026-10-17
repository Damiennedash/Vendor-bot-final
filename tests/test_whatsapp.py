import app.whatsapp as whatsapp


def test_notification_uses_configured_template(monkeypatch):
    sent = []
    monkeypatch.setenv("WHATSAPP_NOTIFICATION_TEMPLATE", "alerte_vente_fanmilk")
    monkeypatch.setenv("WHATSAPP_NOTIFICATION_LANGUAGE", "fr")
    monkeypatch.setattr(whatsapp, "_post", lambda to, payload: sent.append((to, payload)) or True)

    assert whatsapp.send_notification(
        "+228 90 00 00 00", "Nouvelle vente", "Afi a déclaré 20 000 FCFA"
    ) is True

    payload = sent[0][1]
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "alerte_vente_fanmilk"
    assert payload["template"]["language"]["code"] == "fr"
    assert payload["template"]["components"][0]["parameters"][0]["text"] == (
        "Nouvelle vente Afi a déclaré 20 000 FCFA"
    )


def test_notification_falls_back_to_text_without_template(monkeypatch):
    monkeypatch.delenv("WHATSAPP_NOTIFICATION_TEMPLATE", raising=False)
    sent = []
    monkeypatch.setattr(whatsapp, "send_message", lambda to, text: sent.append((to, text)) or True)

    assert whatsapp.send_notification("22890000000", "Incident", "Besoin d'aide", urgent=True)
    assert sent == [("22890000000", "URGENCE - Incident\n\nBesoin d'aide")]


def test_template_collapses_forbidden_whitespace(monkeypatch):
    sent = []
    monkeypatch.setattr(whatsapp, "_post", lambda to, payload: sent.append(payload) or True)
    whatsapp.send_template("22870452612", "alerte", ["Vente\n\nAfi\t     20000"])
    assert sent[0]["template"]["components"][0]["parameters"][0]["text"] == "Vente Afi 20000"


def test_local_togo_phone_gets_country_code(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(whatsapp, "_get_url", lambda: "https://example.test/messages")
    # Supply a nonempty mocked header; no real network request is made.
    monkeypatch.setattr(whatsapp, "_headers", lambda: {"test": "test"})
    post = Mock(return_value=Mock(ok=True))
    monkeypatch.setattr(whatsapp.requests, "post", post)
    assert whatsapp.send_message("70 45 26 12", "Test")
    assert post.call_args.kwargs["json"]["to"] == "22870452612"
