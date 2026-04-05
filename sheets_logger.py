import os
import json
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME = "Orders"
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
    """
    Authenticates with Google Sheets.
    Production (Railway): reads from GOOGLE_CREDENTIALS_JSON env variable.
    Development (local): reads from google_credentials.json file.
    """
    try:
        creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")

        if creds_json:
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(
                "google_credentials.json", scopes=SCOPES
            )

        service = build("sheets", "v4", credentials=creds)
        return service.spreadsheets()

    except Exception as e:
        print(f"❌ Google Auth Error: {e}")
        return None


def setup_sheet_headers():
    """Sets up column headers on first run. Safe to call on every startup."""
    try:
        sheet = _get_sheets_service()
        if not sheet:
            print("⚠ Sheets unavailable — skipping header setup")
            return

        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1:G1",
        ).execute()

        if result.get("values"):
            print("✓ Sheet headers already exist")
            return

        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [COLUMNS]},
        ).execute()

        print("✓ Google Sheet headers created")

    except Exception as e:
        print(f"⚠ Header setup failed: {e}")


def log_order(
    phone: str,
    order_items: str,
    total: str,
    order_type: str,
    raw_message: str,
    status: str = "New",   # "New" or "COMPLAINT"
):
    """
    Appends one row to the Google Sheet for every confirmed order.
    Never crashes the bot — all errors are caught.
    """
    try:
        sheet = _get_sheets_service()
        if not sheet:
            print(f"⚠ Cannot log order for {phone} — Sheets unavailable")
            return

        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            phone,
            order_items,
            total,
            order_type,
            raw_message[:300],
            status,
        ]

        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        print(f"✓ {status} logged for: {phone} — {order_items}")

    except Exception as e:
        print(f"⚠ Logging failed for {phone}: {e}")