import os
import json
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- CONFIGURATION ---
SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME = "Orders"
GOOGLE_JSON_STR = os.getenv("GOOGLE_CREDENTIALS_JSON")
CREDENTIALS_FILE = "google_credentials.json"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Updated columns to match the new business logic
COLUMNS = [
    "Timestamp",
    "Phone",
    "Order Items",
    "Total (KES)",
    "Order Type",
    "Raw Message",
    "Status",  # This will now hold "New" or "COMPLAINT"
]

def _get_sheets_service():
    """Helper to authenticate with Google Sheets API."""
    try:
        if GOOGLE_JSON_STR:
            # Use credentials from Railway environment variable
            creds_dict = json.loads(GOOGLE_JSON_STR)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        else:
            # Fallback for local development
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)

        service = build("sheets", "v4", credentials=creds)
        return service.spreadsheets()

    except Exception as e:
        print("❌ Google Auth Error:", e)
        return None

def setup_sheet_headers():
    """Ensures the sheet has the correct headers on startup."""
    try:
        sheet = _get_sheets_service()
        if not sheet:
            return

        # Check if row 1 already has content
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1:G1",
        ).execute()

        if result.get("values"):
            return # Headers already exist

        # If empty, create headers
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [COLUMNS]},
        ).execute()
        print("✓ Sheet headers ready")

    except Exception as e:
        print("⚠ Header setup failed:", e)

def log_order(phone, order_items, total, order_type, raw_message, status="New"):
    """
    Logs a new order or complaint to the Google Sheet.
    Added 'status' parameter to support the new 'COMPLAINT' detection.
    """
    try:
        sheet = _get_sheets_service()
        if not sheet:
            print("⚠ Cannot log: Google Sheets service unavailable.")
            return

        # Prepare the row data
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            phone,
            order_items,
            total,
            order_type,
            raw_message[:300], # Slightly longer message snippet for context
            status,             # Successfully logs 'New' or 'COMPLAINT'
        ]

        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        print(f"✓ {status} logged for: {phone}")

    except Exception as e:
        print(f"⚠ Logging failed for {phone}: {e}")