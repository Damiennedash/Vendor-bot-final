import os
import json
import logging
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_REPONSES = os.getenv("GOOGLE_SHEET_TAB", "Reponses Vendors")
SHEET_VENDORS = "Vendors"

HEADERS_REPONSES = [
    "Date", "Heure", "Periode", "Telephone", "Nom Vendor", "Depot",
    "Statut Vente", "Ventes FCFA", "FanXtra", "FanChoco", "FanVanille",
    "Lieu de vente", "Categorie Probleme", "Pilier PRIME", "Commentaire", "Source"
]

HEADERS_VENDORS = [
    "Telephone", "Nom", "Depot", "Derniere declaration",
    "Dernieres ventes FCFA", "FanXtra", "FanChoco", "FanVanille",
    "Total pieces", "Date dernieres ventes"
]


def _get_service():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise EnvironmentError("GOOGLE_CREDENTIALS_JSON manquant")
    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _ensure_sheet(service, sheet_name, headers):
    meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    existing = [s["properties"]["title"] for s in meta["sheets"]]
    if sheet_name not in existing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
        ).execute()
        logger.info("Onglet {} cree".format(sheet_name))
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="{}!A1:Z1".format(sheet_name)
    ).execute()
    if not result.get("values"):
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range="{}!A1".format(sheet_name),
            valueInputOption="RAW",
            body={"values": [headers]}
        ).execute()
        logger.info("En-tetes crees dans '{}'".format(sheet_name))


def load_vendor_memory():
    try:
        service = _get_service()
        _ensure_sheet(service, SHEET_VENDORS, HEADERS_VENDORS)
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="{}!A2:J".format(SHEET_VENDORS)
        ).execute()
        rows = result.get("values", [])
        memory = {}
        for row in rows:
            if len(row) >= 3:
                phone = row[0]
                memory[phone] = {
                    "nom": row[1] if len(row) > 1 else "",
                    "depot": row[2] if len(row) > 2 else "",
                    "last_montant": row[4] if len(row) > 4 else "",
                    "last_fanxtra": row[5] if len(row) > 5 else "",
                    "last_fanchoco": row[6] if len(row) > 6 else "",
                    "last_fanvanille": row[7] if len(row) > 7 else "",
                    "last_pieces": row[8] if len(row) > 8 else "",
                    "last_date": row[9] if len(row) > 9 else "",
                }
        logger.info("Memoire chargee : {} vendors".format(len(memory)))
        return memory
    except Exception as e:
        logger.error("Erreur chargement memoire : {}".format(e))
        return {}


def save_vendor(phone, nom, depot):
    try:
        service = _get_service()
        _ensure_sheet(service, SHEET_VENDORS, HEADERS_VENDORS)
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="{}!A:A".format(SHEET_VENDORS)
        ).execute()
        phones = [r[0] if r else "" for r in result.get("values", [])]
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        if phone in phones:
            row_num = phones.index(phone) + 1
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range="{}!A{}:D{}".format(SHEET_VENDORS, row_num, row_num),
                valueInputOption="USER_ENTERED",
                body={"values": [[phone, nom, depot, now]]}
            ).execute()
        else:
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range="{}!A1".format(SHEET_VENDORS),
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [[phone, nom, depot, now, "", "", "", "", "", ""]]}
            ).execute()
        logger.info("Vendor sauvegarde : {} - {}".format(phone, nom))
    except Exception as e:
        logger.error("Erreur sauvegarde vendor : {}".format(e))


def update_vendor_sales(phone, montant, pieces, date, fanxtra="0", fanchoco="0", fanvanille="0"):
    try:
        service = _get_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="{}!A:A".format(SHEET_VENDORS)
        ).execute()
        phones = [r[0] if r else "" for r in result.get("values", [])]
        if phone in phones:
            row_num = phones.index(phone) + 1
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range="{}!E{}:J{}".format(SHEET_VENDORS, row_num, row_num),
                valueInputOption="USER_ENTERED",
                body={"values": [[montant, fanxtra, fanchoco, fanvanille, pieces, date]]}
            ).execute()
            logger.info("Ventes mises a jour pour {}".format(phone))
    except Exception as e:
        logger.error("Erreur update ventes : {}".format(e))


def append_row(row):
    try:
        service = _get_service()
        _ensure_sheet(service, SHEET_REPONSES, HEADERS_REPONSES)
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="{}!A1".format(SHEET_REPONSES),
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]}
        ).execute()
        logger.info("Ligne ajoutee : {}".format(row))
        return True
    except Exception as e:
        logger.error("Erreur Google Sheets : {}".format(e))
        return False
