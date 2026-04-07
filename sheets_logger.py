"""
Google Sheets Order Logger
===========================
Multi-client ready — accepts sheet_id and owner_number as arguments.
Each restaurant logs to their own sheet and notifies their own owner.
"""

import os
import json
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from twilio.rest import Client as TwilioClient

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_NAME = "Orders"

COLUMNS = [
    "Timestamp",
    "Phone",
    "Order Items",
    "Total (KES)",
    "Order Type",
    "Location",
    "Raw Message",
    "Status",
]

TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM  = "whatsapp:+14155238886"


def _get_sheets_service():
    """Authenticates with Google Sheets API."""
    try:
        creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if creds_json:
            creds = Credentials.from_service_account_info(
                json.loads(creds_json), scopes=SCOPES
            )
        else:
            creds = Credentials.from_service_account_file(
                "google_credentials.json", scopes=SCOPES
            )
        return build("sheets", "v4", credentials=creds).spreadsheets()
    except Exception as e:
        print(f"❌ Google Auth Error: {e}")
        return None


def setup_sheet_headers(sheet_id: str):
    """
    Sets up column headers for a specific sheet.
    Call once per client on startup.
    """
    try:
        sheet = _get_sheets_service()
        if not sheet:
            return

        result = sheet.values().get(
            spreadsheetId=sheet_id,
            range=f"{SHEET_NAME}!A1:H1",
        ).execute()

        if result.get("values"):
            return  # Headers already exist

        sheet.values().update(
            spreadsheetId=sheet_id,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [COLUMNS]},
        ).execute()

        print(f"✓ Sheet headers created for sheet: {sheet_id[:20]}...")

    except Exception as e:
        print(f"⚠ Header setup failed for {sheet_id[:20]}: {e}")


def _notify_owner(
    owner_number: str,
    phone: str,
    order_items: str,
    total: str,
    order_type: str,
    location: str,
    timestamp: str,
    status: str,
    restaurant_name: str,
):
    """
    Sends ONE WhatsApp notification to the restaurant owner.
    Only called when is_order is True — never for regular messages.
    This protects your Twilio daily message limit.
    """
    if not owner_number:
        print("⚠ No owner number configured — skipping notification")
        return

    if not TWILIO_SID or not TWILIO_TOKEN:
        print("⚠ Twilio credentials missing — skipping notification")
        return

    try:
        emoji = "🚨" if status == "COMPLAINT" else "🔔"
        status_line = "COMPLAINT — Please follow up!" if status == "COMPLAINT" else "New order received ✅"

        body = (
            f"{emoji} *{restaurant_name} — {status_line}*\n\n"
            f"👤 Customer: {phone}\n"
            f"🍽️ Items: {order_items}\n"
            f"💰 Total: {total}\n"
            f"📦 Type: {order_type}\n"
            f"📍 Location: {location}\n"
            f"🕐 Time: {timestamp}"
        )

        TwilioClient(TWILIO_SID, TWILIO_TOKEN).messages.create(
            from_=TWILIO_FROM,
            to=f"whatsapp:{owner_number}",
            body=body,
        )
        print(f"✓ Owner notified at {owner_number}")

    except Exception as e:
        print(f"⚠ Owner notification failed: {e}")


def log_order(
    phone: str,
    order_items: str,
    total: str,
    order_type: str,
    raw_message: str,
    sheet_id: str,          # ← per-client sheet ID passed as argument
    owner_number: str,      # ← per-client owner number passed as argument
    restaurant_name: str,   # ← for the owner notification message
    status: str = "New",
    location: str = "Not specified",
):
    """
    1. Logs order to the correct Google Sheet for this restaurant.
    2. Notifies this restaurant's owner on WhatsApp.

    Both steps are independent — failure in one never affects the other.
    Owner is only notified when this function is called (is_order = True).
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logged_to_sheet = False

    # ── Step 1: Log to Google Sheets ──────────────────────────────────────────
    try:
        sheet = _get_sheets_service()
        if not sheet:
            print(f"⚠ Sheets unavailable — cannot log for {phone}")
        else:
            row = [
                timestamp,
                phone,
                order_items,
                total,
                order_type,
                location,
                raw_message[:300],
                status,
            ]

            sheet.values().append(
                spreadsheetId=sheet_id,
                range=f"{SHEET_NAME}!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()

            logged_to_sheet = True
            print(f"✓ {status} logged — {phone}: {order_items}")

    except Exception as e:
        print(f"⚠ Sheet logging failed for {phone}: {e}")

    # ── Step 2: Notify Owner (only if sheet log succeeded) ───────────────────
    # We only notify if the order was actually logged — prevents ghost notifications
    if logged_to_sheet:
        _notify_owner(
            owner_number=owner_number,
            phone=phone,
            order_items=order_items,
            total=total,
            order_type=order_type,
            location=location,
            timestamp=timestamp,
            status=status,
            restaurant_name=restaurant_name,
        )
