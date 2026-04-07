import os
import json
from fastapi import FastAPI, Form
from fastapi.responses import Response
from openai import OpenAI
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
from sheets_logger import log_order, setup_sheet_headers
from restaurant_configs import get_restaurant_config, build_system_prompt

load_dotenv()

# ── Startup Validation ─────────────────────────────────────────────────────────
REQUIRED = ["OPENAI_API_KEY", "GOOGLE_CREDENTIALS_JSON", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]
missing = [v for v in REQUIRED if not os.getenv(v)]
if missing:
    raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# Initialize Twilio Client for owner notifications
twilio_client = TwilioClient(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
app = FastAPI()

# ── Conversation Memory ────────────────────────────────────────────────────────
conversation_memory = {}
MAX_HISTORY = 10

def get_history(phone: str) -> list:
    if phone not in conversation_memory:
        conversation_memory[phone] = []
    return conversation_memory[phone]

def save_to_history(phone: str, role: str, content: str):
    history = get_history(phone)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        conversation_memory[phone] = history[-MAX_HISTORY:]


# ── Order Detection & Notification ─────────────────────────────────────────────
ORDER_DETECTION_PROMPT = """
You are an order extraction assistant for a restaurant WhatsApp bot.
Read the conversation and determine if the bot's latest reply contains a CONFIRMED ORDER.
A confirmed order means the bot listed specific items with quantities and a total price.

If there IS a confirmed order extract:
- items: clean summary like "2x Biryani Chicken, 1x Dawa"
- total: just the number like "930"
- order_type: "Delivery", "Dine-in", or "Unknown"
- location: customer delivery location or landmark if mentioned, else "Not specified"
- is_complaint: true if customer expressed dissatisfaction, false otherwise

If NO confirmed order, return is_order as false.

Reply ONLY with valid JSON. No extra text.
"""

def _notify_owner_safely(owner_number, items, total, customer_phone):
    """
    Sends a notification to the owner while fixing common formatting errors.
    """
    try:
        # Clean the number to prevent "whatsapp:whatsapp:+..."
        clean_number = str(owner_number).replace("whatsapp:", "").strip()
        formatted_to = f"whatsapp:{clean_number}"
        
        # Ensure the sender number also has the prefix
        from_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
        if not from_number.startswith("whatsapp:"):
            from_number = f"whatsapp:{from_number}"

        message_body = f"🔔 NEW ORDER!\n\n📍 Customer: {customer_phone}\n🛒 Items: {items}\n💰 Total: KES {total}\n\nCheck Google Sheets for details."

        twilio_client.messages.create(
            from_=from_number,
            to=formatted_to,
            body=message_body
        )
        print(f"✓ Owner notified at {formatted_to}")
    except Exception as e:
        print(f"⚠ Owner notification failed for {owner_number}: {e}")

def detect_and_log_order(phone: str, history: list, raw_message: str, config: dict):
    try:
        recent = history[-6:] if len(history) >= 6 else history
        conversation_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in recent)

        result = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ORDER_DETECTION_PROMPT},
                {"role": "user", "content": conversation_text},
            ],
            max_tokens=150,
        )

        parsed = json.loads(result.choices[0].message.content.strip())

        if not parsed.get("is_order"):
            return

        items = parsed.get("items", "").strip()
        total = parsed.get("total", "").strip()

        if not items or not total or total == "0":
            return

        # Deduplicate
        last = getattr(detect_and_log_order, "_last", {})
        key = f"{phone}:{items}:{total}"
        if last.get("key") == key:
            print(f"⚠ Duplicate skipped for {phone}")
            return
        detect_and_log_order._last = {"key": key}

        status = "COMPLAINT" if parsed.get("is_complaint") else "New"

        # 1. Log to Google Sheets
        log_order(
            phone=phone,
            order_items=items,
            total=f"KES {total}",
            order_type=parsed.get("order_type", "Unknown"),
            raw_message=raw_message,
            sheet_id=config["sheet_id"],
            owner_number=config["owner_number"],
            restaurant_name=config["name"],
            status=status,
            location=parsed.get("location", "Not specified"),
        )

        # 2. Notify the Owner via WhatsApp
        _notify_owner_safely(config["owner_number"], items, total, phone)

    except Exception as e:
        print(f"⚠ Order detection error: {e}")


# ── Startup & Routes ───────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    print("Starting Multi-Client Restaurant Bot...")
    from restaurant_configs import RESTAURANT_CONFIGS
    for number, config in RESTAURANT_CONFIGS.items():
        if config.get("sheet_id"):
            setup_sheet_headers(config["sheet_id"])
            print(f"✓ {config['name']} ready")
    print("✓ All restaurants online")

@app.get("/")
def health():
    from restaurant_configs import RESTAURANT_CONFIGS
    return {"status": "online", "restaurants": [c["name"] for c in RESTAURANT_CONFIGS.values()]}

@app.post("/webhook/whatsapp")
async def reply(From: str = Form(...), To: str = Form(...), Body: str = Form(...)):
    phone = From.replace("whatsapp:", "").strip()
    message = Body.strip()
    config = get_restaurant_config(To)
    system_prompt = build_system_prompt(config)

    if not message:
        twiml = MessagingResponse()
        twiml.message("Samahani, sijapokea ujumbe wako. Tafadhali jaribu tena 😊")
        return Response(content=str(twiml), media_type="application/xml")

    try:
        save_to_history(phone, "user", message)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}, *get_history(phone)],
            max_tokens=500,
            temperature=0.7,
        )
        ai_msg = response.choices[0].message.content
        save_to_history(phone, "assistant", ai_msg)

        detect_and_log_order(phone=phone, history=get_history(phone), raw_message=message, config=config)

    except Exception as e:
        print(f"❌ Error for {phone}: {e}")
        ai_msg = f"Pole sana! Experienced a small hitch 🙏\nPlease call us: {config.get('phone', '')}"

    twiml = MessagingResponse()
    twiml.message(ai_msg)
    return Response(content=str(twiml), media_type="application/xml")

@app.get("/memory/check")
def check_memory():
    return {"active_conversations": len(conversation_memory)}