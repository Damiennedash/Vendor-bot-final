# -*- coding: utf-8 -*-
"""
Envoi de messages via WhatsApp Cloud API (Meta).
Supporte : texte simple, boutons (max 3), liste interactive (max 10)
"""
import os
import requests
import logging
logger = logging.getLogger(__name__)
WA_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
API_VERSION = "v19.0"


def _get_url():
    phone_id = PHONE_ID or os.getenv("WHATSAPP_PHONE_ID")
    if not phone_id:
        logger.error("WHATSAPP_PHONE_ID not set")
        return None
    return f"https://graph.facebook.com/{API_VERSION}/{phone_id}/messages"


def _headers():
    token = WA_TOKEN or os.getenv("WHATSAPP_TOKEN")
    if not token:
        logger.error("WHATSAPP_TOKEN not set")
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

def send_message(to, text):
   """Envoie un message texte simple."""
   payload = {
       "messaging_product": "whatsapp",
       "recipient_type":    "individual",
       "to":                to,
       "type":              "text",
       "text":              {"preview_url": False, "body": text},
   }
   return _post(to, payload)

def send_buttons(to, body, buttons):
   """
   Envoie un message avec boutons interactifs (max 3).
   buttons = [{"id": "oui", "title": "Oui"}, ...]
   """
   payload = {
       "messaging_product": "whatsapp",
       "recipient_type":    "individual",
       "to":                to,
       "type":              "interactive",
       "interactive": {
           "type": "button",
           "body": {"text": body},
           "action": {
               "buttons": [
                   {
                       "type": "reply",
                       "reply": {
                           "id":    b["id"],
                           "title": b["title"][:20]
                       }
                   }
                   for b in buttons[:3]
               ]
           }
       }
   }
   return _post(to, payload)

def send_list(to, body, button_label, sections):
   """
   Envoie une liste interactive (max 10 options).
   sections = [{"title": "...", "rows": [{"id": "1", "title": "...", "description": "..."}]}]
   """
   payload = {
       "messaging_product": "whatsapp",
       "recipient_type":    "individual",
       "to":                to,
       "type":              "interactive",
       "interactive": {
           "type": "list",
           "body": {"text": body},
           "action": {
               "button":   button_label[:20],
               "sections": sections
           }
       }
   }
   return _post(to, payload)

def _post(to, payload):
    url = _get_url()
    headers = _headers()
    if not url or not headers:
        return False

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        if not r.ok:
            # Le corps Meta contient le code precis (token, permission ou
            # numero). Il ne contient jamais le jeton envoye dans l'entete.
            logger.error(
                "Echec envoi WhatsApp à %s: HTTP %s - %s",
                to,
                r.status_code,
                r.text[:1000],
            )
            return False
        logger.info("Message envoyé à %s OK", to)
        return True
    except requests.RequestException as e:
        logger.error("Echec envoi WhatsApp à %s: %s", to, e)
        return False
