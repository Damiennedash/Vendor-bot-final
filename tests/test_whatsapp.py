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
        "Nouvelle vente\n\nAfi a déclaré 20 000 FCFA"
    )


def test_notification_falls_back_to_text_without_template(monkeypatch):
    monkeypatch.delenv("WHATSAPP_NOTIFICATION_TEMPLATE", raising=False)
    sent = []
    monkeypatch.setattr(whatsapp, "send_message", lambda to, text: sent.append((to, text)) or True)

    assert whatsapp.send_notification("22890000000", "Incident", "Besoin d'aide", urgent=True)
    assert sent == [("22890000000", "URGENCE - Incident\n\nBesoin d'aide")]
