import os
import json
from fastapi import FastAPI, Form
from fastapi.responses import Response
from openai import OpenAI
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse
from sheets_logger import log_order, setup_sheet_headers

load_dotenv()

# ── INIT ─────────────────────────────────────────────
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI()

# ── MEMORY ───────────────────────────────────────────
conversation_memory = {}
MAX_HISTORY = 12  # reduced for speed

def get_history(phone: str):
    return conversation_memory.setdefault(phone, [])

def save_to_history(phone: str, role: str, content: str):
    history = get_history(phone)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        conversation_memory[phone] = history[-MAX_HISTORY:]

# ── ORDER DETECTION ──────────────────────────────────
ORDER_DETECTION_PROMPT = """
Detect if the assistant CONFIRMED an order.

Return ONLY JSON:
{"is_order": true, "items": "...", "total": "...", "order_type": "..."}
OR
{"is_order": false}
"""

def detect_and_log_order(phone, history, raw_message):
    try:
        recent = history[-4:]
        conversation_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in recent
        )

        result = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ORDER_DETECTION_PROMPT},
                {"role": "user", "content": conversation_text},
            ],
            max_tokens=120,
        )

        raw = result.choices[0].message.content.strip()

        try:
            parsed = json.loads(raw)
        except:
            print("⚠ JSON parse failed:", raw)
            return

        if parsed.get("is_order"):
            log_order(
                phone=phone,
                order_items=parsed.get("items", ""),
                total=f"KES {parsed.get('total', '')}",
                order_type=parsed.get("order_type", "Unknown"),
                raw_message=raw_message,
            )

    except Exception as e:
        print("⚠ Order detection error:", e)

# ── SYSTEM PROMPT ────────────────────────────────────
SYSTEM_PROMPT = """You are Zidi, the smart, witty, and highly efficient AI Waiter for Zidi Kitchen in Kenya.

Be friendly, Kenyan, and concise. Mix English, Swahili, and Sheng naturally.

RULES:
- Always confirm orders clearly with total price
- Ask for location for delivery
- Keep replies short (WhatsApp style)
- Never invent menu items
- Handle complaints politely
- If unclear: "Sijashika hapo vizuri, unaweza repeat tafadhali?"

When confirming orders, clearly list:
Items, Total, Type (Delivery/Dine-in)
"""

# ── STARTUP ──────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    print("Starting Zidi Kitchen Bot...")
    setup_sheet_headers()
    print("✓ Bot ready")

# ── ROUTES ───────────────────────────────────────────
@app.get("/")
def home():
    return {"status": "Bot is running"}

@app.post("/webhook/whatsapp")
async def reply(From: str = Form(...), Body: str = Form(...)):
    phone = From.replace("whatsapp:", "").strip()
    message = Body.strip()

    save_to_history(phone, "user", message)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *get_history(phone),
    ]

    # ✅ SAFE AI CALL
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=250,
        )
        ai_msg = response.choices[0].message.content

    except Exception as e:
        print("❌ OpenAI Error:", e)
        ai_msg = "Samahani, kuna delay kidogo. Try again shortly 🙏"

    save_to_history(phone, "assistant", ai_msg)

    detect_and_log_order(phone, get_history(phone), message)

    twiml = MessagingResponse()
    twiml.message(ai_msg)

    return Response(content=str(twiml), media_type="application/xml")

# ── DEBUG ────────────────────────────────────────────
@app.get("/memory/check")
def check_memory():
    return {
        "active_conversations": len(conversation_memory),
        "customers": list(conversation_memory.keys()),
    }