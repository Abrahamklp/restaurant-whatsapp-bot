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
    """Sets up column headers for a specific sheet on startup."""
    try:
        sheet = _get_sheets_service()
        if not sheet:
            return

        result = sheet.values().get(
            spreadsheetId=sheet_id,
            range=f"{SHEET_NAME}!A1:H1",
        ).execute()

        if result.get("values"):
            print(f"✓ Sheet headers already exist for: {sheet_id[:20]}...")
            return

        sheet.values().update(
            spreadsheetId=sheet_id,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [COLUMNS]},
        ).execute()

        print(f"✓ Sheet headers created for: {sheet_id[:20]}...")

    except Exception as e:
        print(f"⚠ Header setup failed: {e}")
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
    Only called when is_order is True — protects Twilio daily limit.
    """
    # ── GATE CHECKS ────────────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"🔔 _notify_owner called")
    print(f"   owner_number   : '{owner_number}'")
    print(f"   restaurant     : '{restaurant_name}'")
    print(f"   TWILIO_SID     : '{TWILIO_SID[:10]}...' " if TWILIO_SID else "   TWILIO_SID     : NOT SET ❌")
    print(f"   TWILIO_TOKEN   : '{TWILIO_TOKEN[:10]}...' " if TWILIO_TOKEN else "   TWILIO_TOKEN   : NOT SET ❌")
    print(f"   TWILIO_FROM    : '{TWILIO_FROM}'")
    print(f"{'='*50}")

    if not owner_number:
        print("⚠ SKIP: owner_number is empty or None")
        print("  Fix: Set ZIDI_OWNER_NUMBER in Railway variables")
        return

    if not TWILIO_SID:
        print("⚠ SKIP: TWILIO_ACCOUNT_SID not set")
        print("  Fix: Add TWILIO_ACCOUNT_SID to Railway variables")
        return

    if not TWILIO_TOKEN:
        print("⚠ SKIP: TWILIO_AUTH_TOKEN not set")
        print("  Fix: Add TWILIO_AUTH_TOKEN to Railway variables")
        return

    # ── BUILD MESSAGE ──────────────────────────────────────────────────────────
    emoji = "🚨" if status == "COMPLAINT" else "🔔"
    status_line = "COMPLAINT — Follow up needed!" if status == "COMPLAINT" else "New order ✅"

    body = (
        f"{emoji} *{restaurant_name} — {status_line}*\n\n"
        f"👤 Customer: {phone}\n"
        f"🍽️ Items: {order_items}\n"
        f"💰 Total: {total}\n"
        f"📦 Type: {order_type}\n"
        f"📍 Location: {location}\n"
        f"🕐 Time: {timestamp}"
    )

    to_number = f"whatsapp:{owner_number}"

    # ── SEND ───────────────────────────────────────────────────────────────────
    print(f"📤 Attempting send:")
    print(f"   from : {TWILIO_FROM}")
    print(f"   to   : {to_number}")
    print(f"   body : {body[:80]}...")

    try:
        twilio_client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        msg = twilio_client.messages.create(
            from_=TWILIO_FROM,
            to=to_number,
            body=body,
        )

        # If we reach here — Twilio accepted the message
        print(f"✅ TWILIO ACCEPTED — SID: {msg.sid} | Status: {msg.status}")
        print(f"   If message not received, check Twilio Console → Monitor → Logs → {msg.sid}")

    except Exception as e:
        print(f"❌ TWILIO REJECTED — {type(e).__name__}: {e}")
        traceback.print_exc()
        print("\n  Possible causes:")
        print(f"  1. +{owner_number} has not joined sandbox (send 'join ten-walk' to +14155238886)")
        print(f"  2. Daily 50-message limit exceeded (check Twilio Console)")
        print(f"  3. Twilio credentials are wrong or expired")
        print(f"  4. Number format issue — expected: +254XXXXXXXXX (no spaces)")


def log_order(
    phone: str,
    order_items: str,
    total: str,
    order_type: str,
    raw_message: str,
    sheet_id: str,
    owner_number: str,
    restaurant_name: str,
    status: str = "New",
    location: str = "Not specified",
):
    """
    1. Logs order to this restaurant's Google Sheet.
    2. Notifies this restaurant's owner on WhatsApp.
    Both steps run independently — failure in one never blocks the other.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n{'='*50}")
    print(f"📋 log_order called")
    print(f"   phone          : {phone}")
    print(f"   items          : {order_items}")
    print(f"   total          : {total}")
    print(f"   sheet_id       : {sheet_id[:20] + '...' if sheet_id else 'NOT SET ❌'}")
    print(f"   owner_number   : '{owner_number}'")
    print(f"   restaurant     : '{restaurant_name}'")
    print(f"   status         : {status}")
    print(f"{'='*50}")

    # ── Step 1: Log to Google Sheets ──────────────────────────────────────────
    logged = False
    try:
        if not sheet_id:
            print("⚠ sheet_id is empty — cannot log to sheet")
        else:
            sheet = _get_sheets_service()
            if not sheet:
                print("⚠ Sheets service unavailable")
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

                logged = True
                print(f"✅ Sheet logged: {order_items} for {phone}")

    except Exception as e:
        print(f"❌ Sheet logging failed: {e}")
        traceback.print_exc()

    # ── Step 2: Notify Owner ──────────────────────────────────────────────────
    # Fires regardless of sheet logging success
    print(f"\n📨 Proceeding to owner notification (sheet_logged={logged})")
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