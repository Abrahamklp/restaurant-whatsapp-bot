"""
Google Sheets Order Logger
==========================
Every time a customer confirms an order, this module
appends one new row to your Google Sheet with:
- Timestamp
- Customer phone number
- Order items
- Total price (if detected)
- Order type (delivery / dine-in / unknown)
- The customer's raw message (for reference)
"""

import os
import json
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


# ── Config ─────────────────────────────────────────────────────────────────────
# These come from your .env file
SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")         # The long ID in your sheet URL
SHEET_NAME = "Orders"                                   # Tab name inside the sheet
CREDENTIALS_FILE = "google_credentials.json"           # Service account key file

# Columns in the sheet — in this exact order
COLUMNS = [
    "Timestamp",
    "Phone",
    "Order Items",
    "Total (KES)",
    "Order Type",
    "Raw Message",
    "Status",
]

# Google API scopes we need
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_sheets_service():
    """
    Authenticates with Google using the service account credentials file
    and returns a Sheets API service object.
    """
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
    )
    service = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()


def setup_sheet_headers():
    """
    Call this once on startup to make sure the sheet has the correct headers.
    If row 1 is already filled, it does nothing.
    """
    try:
        sheet = _get_sheets_service()

        # Check if headers already exist
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1:G1",
        ).execute()

        existing = result.get("values", [])
        if existing:
            return  # Headers already set — do nothing

        # Write headers to row 1
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
    """
    Appends one new row to the Google Sheet with the order details.
    Called automatically whenever the bot confirms an order.

    Args:
        phone:       Customer's phone number
        order_items: What they ordered (e.g. "2x Biryani, 1x Dawa")
        total:       Total price string (e.g. "KES 930") or "" if unknown
        order_type:  "Delivery", "Dine-in", or "Unknown"
        raw_message: The customer's original message text
    """
    try:
        sheet = _get_sheets_service()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        row = [
            timestamp,
            phone,
            order_items,
            total,
            order_type,
            raw_message[:200],  # Trim very long messages
            "New",              # Default status — owner can change to "Confirmed", "Done" etc.
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
        # Never crash the bot if sheet logging fails
        # The customer still gets their reply — logging is non-blocking
        print(f"⚠ Sheet logging failed (bot still works): {e}")