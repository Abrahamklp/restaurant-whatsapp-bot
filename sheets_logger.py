import os
import json
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from twilio.rest import Client as TwilioClient

# ── Google Sheets Config ───────────────────────────────────────────────────────
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

# ── Twilio Config ──────────────────────────────────────────────────────────────
TWILIO_SID    = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM   = "whatsapp:+14155238886"   # Your Twilio sandbox number

# The owner's WhatsApp number — receives a notification on every new order
# Set this as an environment variable OWNER_WHATSAPP_NUMBER in Railway and .env
# Format: +254712345678  (no spaces, include country code)
OWNER_NUMBER  = os.getenv("OWNER_WHATSAPP_NUMBER")


# ── Google Sheets Auth ─────────────────────────────────────────────────────────
def _get_sheets_service():
    """
    Authenticates with Google Sheets.
    Production: reads from GOOGLE_CREDENTIALS_JSON env variable.
    Development: reads from google_credentials.json file.
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


# ── WhatsApp Owner Notification ────────────────────────────────────────────────
def _notify_owner(
    phone: str,
    order_items: str,
    total: str,
    order_type: str,
    location: str,
    timestamp: str,
    status: str,
):
    """
    Sends a WhatsApp notification to the restaurant owner
    every time a new order is confirmed.
    Silently skips if OWNER_WHATSAPP_NUMBER is not set.
    Never crashes the bot — all errors are caught.
    """
    if not OWNER_NUMBER:
        print("⚠ OWNER_WHATSAPP_NUMBER not set — skipping owner notification")
        return

    if not TWILIO_SID or not TWILIO_TOKEN:
        print("⚠ Twilio credentials missing — skipping owner notification")
        return

    try:
        # Build the notification message
        emoji = "🚨" if status == "COMPLAINT" else "🔔"
        status_line = "⚠️ COMPLAINT — Please follow up!" if status == "COMPLAINT" else "✅ New order received"

        message_body = (
            f"{emoji} *ZIDI KITCHEN — {status_line}*\n\n"
            f"👤 Customer: {phone}\n"
            f"🍽️ Items: {order_items}\n"
            f"💰 Total: {total}\n"
            f"📦 Type: {order_type}\n"
            f"📍 Location: {location}\n"
            f"🕐 Time: {timestamp}\n\n"
            f"Reply to customer on WhatsApp or call them directly."
        )

        twilio_client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        twilio_client.messages.create(
            from_=TWILIO_FROM,
            to=f"whatsapp:{OWNER_NUMBER}",
            body=message_body,
        )

        print(f"✓ Owner notified — {phone}: {order_items}")

    except Exception as e:
        # Never crash the bot if notification fails
        print(f"⚠ Owner notification failed (order still logged): {e}")


# ── Sheet Setup ────────────────────────────────────────────────────────────────
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


# ── Main Log Function ──────────────────────────────────────────────────────────
def log_order(
    phone: str,
    order_items: str,
    total: str,
    order_type: str,
    raw_message: str,
    status: str = "New",
    location: str = "Not specified",
):
    """
    1. Appends one row to Google Sheets.
    2. Sends a WhatsApp notification to the owner.
    Both steps are independent — if one fails, the other still runs.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Step 1: Log to Google Sheets ──
    try:
        sheet = _get_sheets_service()
        if not sheet:
            print(f"⚠ Cannot log order for {phone} — Sheets unavailable")
        else:
            row = [
                timestamp,
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

            print(f"✓ {status} logged to sheet — {phone}: {order_items}")

    except Exception as e:
        print(f"⚠ Sheet logging failed for {phone}: {e}")

    # ── Step 2: Notify Owner on WhatsApp ──
    _notify_owner(
        phone=phone,
        order_items=order_items,
        total=total,
        order_type=order_type,
        location=location,
        timestamp=timestamp,
        status=status,
    )