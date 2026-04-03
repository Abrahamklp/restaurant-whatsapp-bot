import os
import json
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ── Config ─────────────────────────────────────────────────────────────────────
SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME = "Orders"
# We'll try to get the JSON string from Railway variables first
GOOGLE_JSON_STR = os.getenv("GOOGLE_CREDENTIALS_JSON")
# Fallback filename for local testing
CREDENTIALS_FILE = "google_credentials.json"

COLUMNS = [
    "Timestamp",
    "Phone",
    "Order Items",
    "Total (KES)",
    "Order Type",
    "Raw Message",
    "Status",
]

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _get_sheets_service():
    """
    Authenticates with Google using either an environment variable (Railway)
    or a local JSON file (Local Dev).
    """
    if GOOGLE_JSON_STR:
        # RAILWAY MODE: Parse the JSON string from the environment variable
        creds_dict = json.loads(GOOGLE_JSON_STR)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        # LOCAL MODE: Look for the physical file
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        
    service = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()

def setup_sheet_headers():
    try:
        sheet = _get_sheets_service()
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1:G1",
        ).execute()

        existing = result.get("values", [])
        if existing:
            return

        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [COLUMNS]},
        ).execute()

        print("✓ Google Sheet headers created successfully")
    except Exception as e:
        print(f"⚠ Could not set up sheet headers: {e}")

def log_order(phone: str, order_items: str, total: str, order_type: str, raw_message: str):
    try:
        sheet = _get_sheets_service()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [
            timestamp,
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
        print(f"✓ Order logged to sheet — {phone}: {order_items}")
    except Exception as e:
        print(f"⚠ Sheet logging failed: {e}")