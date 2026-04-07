"""
Google Sheets Order Logger
===========================
Multi-client ready — accepts sheet_id and owner_number as arguments.
Each restaurant logs to their own sheet and notifies their own owner.
"""

import os
import json
import traceback
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
        traceback.print_exc()
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
        traceback.print_exc()


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
    # ── DEBUG: Print all relevant env values ──────────────────────────────────
    print(f"DEBUG ► owner_number   = '{owner_number}'")
    print(f"DEBUG ► TWILIO_SID     = '{TWILIO_SID[:8] + '...' if TWILIO_SID else 'NOT SET'}'")
    print(f"DEBUG ► TWILIO_TOKEN   = '{TWILIO_TOKEN[:8] + '...' if TWILIO_TOKEN else 'NOT SET'}'")
    print(f"DEBUG ► TWILIO_FROM    = '{TWILIO_FROM}'")
    print(f"DEBUG ► to (will send) = 'whatsapp:{owner_number}'")

    if not owner_number:
        print("⚠ No owner number configured — skipping notification")
        print("  → Set ZIDI_OWNER_NUMBER or OWNER_WHATSAPP_NUMBER in Railway environment variables")
        return

    if not TWILIO_SID:
        print("⚠ TWILIO_ACCOUNT_SID is not set — skipping notification")
        print("  → Add TWILIO_ACCOUNT_SID to Railway environment variables")
        return

    if not TWILIO_TOKEN:
        print("⚠ TWILIO_AUTH_TOKEN is not set — skipping notification")
        print("  → Add TWILIO_AUTH_TOKEN to Railway environment variables")
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

        print(f"DEBUG ► Attempting Twilio send to whatsapp:{owner_number} ...")

        twilio_client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        msg = twilio_client.messages.create(
            from_=TWILIO_FROM,
            to=f"whatsapp:{owner_number}",
            body=body,
        )

        print(f"✓ Owner notified at {owner_number}")
        print(f"DEBUG ► Twilio message SID: {msg.sid}")
        print(f"DEBUG ► Twilio message status: {msg.status}")

    except Exception as e:
        print(f"⚠ Owner notification failed: {e}")
        print(f"  → Error type: {type(e).__name__}")
        traceback.print_exc()
        print("\n  COMMON FIXES:")
        print("  1. Has +{} sent 'join <keyword>' to the sandbox? (Twilio trial requirement)".format(owner_number))
        print("  2. Is TWILIO_ACCOUNT_SID correct? Check Twilio Console → Account Info")
        print("  3. Is TWILIO_AUTH_TOKEN correct? Check Twilio Console → Account Info")
        print("  4. Is the owner number in E.164 format? e.g. +254713348005 (no spaces)")


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

    # ── DEBUG: Confirm log_order was called ───────────────────────────────────
    print(f"DEBUG ► log_order called for {phone} | items={order_items} | total={total}")
    print(f"DEBUG ► sheet_id={sheet_id[:20] + '...' if sheet_id else 'NOT SET'}")
    print(f"DEBUG ► owner_number={owner_number!r}")
    print(f"DEBUG ► restaurant_name={restaurant_name!r}")

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
        traceback.print_exc()

    # ── Step 2: Notify Owner ──────────────────────────────────────────────────
    # NOTE: Owner notification now fires whether or not sheet logging succeeded.
    # This ensures you always get notified even if Sheets has a temporary issue.
    print(f"DEBUG ► Sheet logged: {logged_to_sheet} — proceeding to owner notification regardless")

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