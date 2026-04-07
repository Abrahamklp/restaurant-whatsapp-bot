import os
import json
from fastapi import FastAPI, Form
from fastapi.responses import Response
from openai import OpenAI
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse
from sheets_logger import log_order, setup_sheet_headers
from restaurant_configs import get_restaurant_config, build_system_prompt

load_dotenv()

# ── Startup Validation ─────────────────────────────────────────────────────────
REQUIRED = ["OPENAI_API_KEY", "GOOGLE_CREDENTIALS_JSON"]
missing = [v for v in REQUIRED if not os.getenv(v)]
if missing:
    raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI()

# ── Conversation Memory ────────────────────────────────────────────────────────
# Key = phone number, Value = list of messages
# Each customer's history is stored separately regardless of which restaurant they contact
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


# ── Order Detection ────────────────────────────────────────────────────────────
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
Examples:
{"is_order": true, "items": "2x Biryani, 1x Dawa", "total": "930", "order_type": "Delivery", "location": "Roysambu near Equity", "is_complaint": false}
{"is_order": false}
"""

def detect_and_log_order(
    phone: str,
    history: list,
    raw_message: str,
    config: dict,
):
    """
    Checks if the latest bot reply contains a confirmed order.
    If yes — logs to this restaurant's sheet and notifies their owner.
    Owner notification ONLY fires here, protecting the daily message limit.
    """
    try:
        recent = history[-6:] if len(history) >= 6 else history
        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in recent
        )

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

        # Skip empty or invalid extractions
        if not items or not total or total == "0" or "..." in items:
            print(f"⚠ Skipping empty order for {phone}")
            return

        # Deduplicate — never log the same order twice in a row
        last = getattr(detect_and_log_order, "_last", {})
        key = f"{phone}:{items}:{total}"
        if last.get("key") == key:
            print(f"⚠ Duplicate skipped for {phone}")
            return
        detect_and_log_order._last = {"key": key}

        status = "COMPLAINT" if parsed.get("is_complaint") else "New"

        # Pass restaurant-specific sheet and owner — multi-client routing
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

    except json.JSONDecodeError:
        print(f"⚠ Order detection: invalid JSON for {phone}")
    except Exception as e:
        print(f"⚠ Order detection error for {phone}: {e}")


# ── Startup ────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    print("Starting Multi-Client Restaurant Bot...")
    from restaurant_configs import RESTAURANT_CONFIGS
    for number, config in RESTAURANT_CONFIGS.items():
        if config.get("sheet_id"):
            setup_sheet_headers(config["sheet_id"])
            print(f"✓ {config['name']} ready")
    print("✓ All restaurants online")


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def health():
    from restaurant_configs import RESTAURANT_CONFIGS
    return {
        "status": "online",
        "restaurants": [c["name"] for c in RESTAURANT_CONFIGS.values()],
    }


@app.post("/webhook/whatsapp")
async def reply(
    From: str = Form(...),   # Customer's number
    To: str = Form(...),     # Twilio number that received the message — used for routing
    Body: str = Form(...),
):
    phone = From.replace("whatsapp:", "").strip()
    message = Body.strip()

    # ── Route to correct restaurant based on which Twilio number was messaged ──
    config = get_restaurant_config(To)
    system_prompt = build_system_prompt(config)

    # Handle empty messages
    if not message:
        twiml = MessagingResponse()
        twiml.message("Samahani, sijapokea ujumbe wako. Tafadhali jaribu tena 😊")
        return Response(content=str(twiml), media_type="application/xml")

    try:
        save_to_history(phone, "user", message)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                *get_history(phone),
            ],
            max_tokens=500,
            temperature=0.7,
        )

        ai_msg = response.choices[0].message.content
        save_to_history(phone, "assistant", ai_msg)

        # Check for confirmed order — only place owner gets notified
        detect_and_log_order(
            phone=phone,
            history=get_history(phone),
            raw_message=message,
            config=config,
        )

    except Exception as e:
        print(f"❌ Error for {phone}: {e}")
        conversation_memory[phone] = []
        ai_msg = (
            "Pole sana! Experienced a small hitch 🙏\n\n"
            f"Please try again or call us: {config.get('phone', '')}"
        )

    twiml = MessagingResponse()
    twiml.message(ai_msg)
    return Response(content=str(twiml), media_type="application/xml")


@app.get("/memory/check")
def check_memory():
    return {
        "active_conversations": len(conversation_memory),
        "customers": [
            {
                "phone": p,
                "messages": len(h),
                "last": h[-1]["content"][:60] + "..." if h else "",
            }
            for p, h in conversation_memory.items()
        ],
    }
