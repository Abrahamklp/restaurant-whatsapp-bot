import os
import json
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME = "Orders"

GOOGLE_JSON_STR = os.getenv("GOOGLE_CREDENTIALS_JSON")
CREDENTIALS_FILE = "google_credentials.json"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

COLUMNS = [
    "Timestamp",
    "Phone",
    "Order Items",
    "Total (KES)",
    "Order Type",
    "Raw Message",
    "Status",
]

def _get_sheets_service():
    try:
        if GOOGLE_JSON_STR:
            creds_dict = json.loads(GOOGLE_JSON_STR)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)

        service = build("sheets", "v4", credentials=creds)
        return service.spreadsheets()

    except Exception as e:
        print("❌ Google Auth Error:", e)
        return None

def setup_sheet_headers():
    try:
        sheet = _get_sheets_service()
        if not sheet:
            return

        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1:G1",
        ).execute()

        if result.get("values"):
            return

        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [COLUMNS]},
        ).execute()

        print("✓ Sheet headers ready")

    except Exception as e:
        print("⚠ Header setup failed:", e)

def log_order(phone, order_items, total, order_type, raw_message):
    try:
        sheet = _get_sheets_service()
        if not sheet:
            return

        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            phone,
            order_items,
            total,
            order_type,
            raw_message[:200],
            "New",
        ]

        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        print(f"✓ Order logged: {phone}")

    except Exception as e:
        print("⚠ Logging failed:", e)