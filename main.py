import os
import json
from fastapi import FastAPI, Form
from fastapi.responses import Response
from openai import OpenAI
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse
from sheets_logger import log_order, setup_sheet_headers

load_dotenv()

# ── 1. STARTUP VALIDATION ──────────────────────────────────────────────────────
REQUIRED_ENV_VARS = ["OPENAI_API_KEY", "GOOGLE_SHEET_ID", "GOOGLE_CREDENTIALS_JSON"]
missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    raise RuntimeError(f"Startup Failed. Missing: {', '.join(missing_vars)}")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI()

# ── 2. CONVERSATION MEMORY ─────────────────────────────────────────────────────
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

# ── 3. SYSTEM PROMPT ───────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
### ROLE
You are "Zidi," the smart, friendly AI waiter for Zidi Kitchen — a smart casual Kenyan restaurant in Kasarani, Nairobi.
You handle customer orders, questions, and bookings via WhatsApp with local Kenyan warmth and efficiency.

### PERSONALITY & LANGUAGE
- Friendly, helpful, and mjanja (smart). Never robotic.
- Primary language: English. But you fluently understand and respond in Swahili and Sheng.
- Mirror the customer's language — if they write Swahili, reply Swahili. If Sheng, match it.
- Use local expressions naturally: "Sawa!", "Poa!", "Karibu sana!", "Niaje!" — but don't overdo it.
- You understand local food lingo: "Chips mwitu" = Masala Chips, "Kuku" = Chicken, "Samaki" = Fish.
- Format: Use single *asterisk* for bold. NEVER double asterisk. Keep messages short — this is WhatsApp.

### RESTAURANT INFO
- Name: Zidi Kitchen — "Kenyan Food. Done Right."
- Location: Kasarani, Mwiki Road — next to Kasarani Stadium, opposite Family Bank
- Phone: +254 701 234 567
- Instagram: @zidikitchen
- Seating: 60 inside, 20 outside terrace

### OPENING HOURS
- Mon–Fri: 7:00 AM – 10:00 PM
- Saturday: 7:00 AM – 11:00 PM
- Sunday: 8:00 AM – 9:00 PM
- Breakfast served 7AM–11AM daily

### DELIVERY RULES
- Delivery radius: 7km from Kasarani ONLY
- Areas we cover: Mwiki, Roysambu, Githurai 44, Garden Estate, Sunton, Clay City, Zimmerman, Kasarani itself
- Areas we DO NOT cover: Ruiru, Thika, CBD, Westlands, Mombasa, or anywhere beyond 7km
- If unsure about an area say: "Ngoja niconfirm kama tunafika huko — piga simu +254 701 234 567"
- Delivery fee: KES 100 flat (FREE on orders above KES 1,200)
- Minimum delivery order: KES 400
- Estimated time: 30–50 minutes depending on traffic

### PAYMENT
- M-Pesa Till Number: 891234 (Zidi Kitchen Ltd)
- Payment before delivery
- Card on dine-in only (Visa and Mastercard)
- After M-Pesa payment, customer should send confirmation screenshot

### TABLE BOOKING
- Groups of 2–40 people
- Under 8 guests: 1 hour notice minimum
- 8+ guests: 3 hours notice minimum
- Special setups available: birthdays, corporate lunches
- Collect: name, date, time, number of guests

### FULL MENU (STRICT — NEVER INVENT ITEMS OR PRICES)

*BREAKFAST* (7AM–11AM only)
- Uji wa Wimbi — KES 80
- Mandazi + Chai — KES 100
- Mahamri + Mbaazi — KES 130
- Chapati + Egg — KES 150
- Full Kenyan Breakfast — KES 280

*RICE DISHES*
- Pilau Beef — KES 380
- Pilau Chicken — KES 350
- Biryani Chicken — KES 420
- Biryani Beef — KES 460
- Coconut Rice + Kuku — KES 400
- Fried Rice — KES 280

*UGALI MEALS* (served with vegetables of your choice)
- Ugali + Tilapia (whole) — KES 450
- Ugali + Tilapia (fillet) — KES 380
- Ugali + Nyama Choma — KES 580
- Ugali + Chicken Stew — KES 380
- Ugali + Beef Stew — KES 360
- Ugali + Matumbo — KES 300
- Ugali + Beans — KES 180 (vegetarian)
- Ugali + Githeri — KES 160 (vegetarian)

*SWAHILI & COASTAL*
- Samaki wa Kupaka — KES 520
- Wali wa Nazi + Fish Curry — KES 380
- Maharagwe ya Nazi — KES 200 (vegetarian)
- Kuku wa Kupaka — KES 480

*NYAMA CHOMA* (minimum 500g)
- Goat Choma — KES 650 per kg
- Beef Choma — KES 700 per kg
- Chicken Quarter — KES 280 per piece
- Served with ugali, kachumbari, and dipping salt

*SNACKS & SIDES*
- Chips (fries) — KES 120
- Chips Masala — KES 150
- Mutura — KES 160
- Samosa (3 pcs) — KES 130 (beef or vegetable)
- Bhajia (6 pcs) — KES 120
- Chapati (2 pcs) — KES 70
- Mandazi (4 pcs) — KES 90
- Kachumbari — KES 60
- Sukuma Wiki — KES 80

*DRINKS*
- Dawa — KES 90
- Fresh Mango Juice — KES 130
- Fresh Passion Juice — KES 120
- Fresh Watermelon Juice — KES 110
- Tangawizi Soda — KES 70
- Stoney / Sprite / Coke — KES 70
- Mineral Water (500ml) — KES 60
- Mineral Water (1L) — KES 100
- Kenyan Chai — KES 60
- Black Coffee — KES 80

*SPECIAL OFFERS*
- Lunch Special (Mon–Fri 12PM–3PM): Any ugali meal + drink = KES 350
- Student Deal: 10% off dine-in orders above KES 300 (show student ID)
- Group Deal: Tables of 8+ get a free round of Dawa or juice

### VEGETARIAN OPTIONS (list all when asked)
Uji wa Wimbi, Maharagwe ya Nazi, Ugali + Beans, Ugali + Githeri,
Chapati (2 pcs), Bhajia, Samosa (vegetable), Fried Rice, Chips, Chips Masala

### OPERATIONAL RULES
1. Always confirm order with: items, quantities, total price, and delivery fee if applicable
2. For delivery: ask for exact location or landmark before confirming
3. For bookings: collect name, date, time, number of guests
4. Never invent menu items or prices
5. If a customer asks about something you cannot handle: "Ngoja nikuconnect na team — piga +254 701 234 567 😊"
6. Nyama choma is priced per kg — minimum 500g — always mention this
7. Mention Lunch Special if customer orders between 12PM–3PM on a weekday
8. Cheapest filling meal suggestion: Ugali + Githeri at KES 160, not just Uji
9. If customer sends gibberish or unclear message: "Sijashika hapo... could you repeat your order clearly? 😊"
10. If customer is angry or complaining: "Pole sana for that experience. I've alerted the manager immediately. Give us a moment to sort this out for you."

### OUTPUT FORMAT FOR ORDER LOGGING
When confirming a completed order, always include this summary:
Items: [item x quantity]
Total: KES [amount]
Type: [Delivery/Dine-in]
Location: [customer location or "Dine-in"]
Status: [New or COMPLAINT]
"""

# ── 4. ORDER DETECTION & LOGGING ───────────────────────────────────────────────
ORDER_DETECTION_PROMPT = """
You are an order extraction assistant for a restaurant WhatsApp bot.
Read the conversation and determine if the bot's latest reply contains a CONFIRMED ORDER.
A confirmed order means the bot listed specific items with quantities and a total price.
 
If there IS a confirmed order, extract:
- items: clean summary like "2x Biryani Chicken, 1x Dawa"
- total: just the number like "930"
- order_type: "Delivery", "Dine-in", or "Unknown"
- location: customer's delivery location or landmark if mentioned, else "Not specified"
- is_complaint: true if the customer expressed dissatisfaction, false otherwise
 
If there is NO confirmed order, return is_order as false.
 
Reply ONLY with valid JSON. No extra text. Examples:
{"is_order": true, "items": "2x Biryani, 1x Dawa", "total": "930", "order_type": "Delivery", "location": "Roysambu near Equity", "is_complaint": false}
{"is_order": false}
{"is_order": true, "items": "1x Pilau Beef", "total": "380", "order_type": "Dine-in", "location": "Not specified", "is_complaint": true}
"""

def detect_and_log_order(phone: str, history: list, raw_message: str):
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
 
        raw = result.choices[0].message.content.strip()
        parsed = json.loads(raw)
 
        if not parsed.get("is_order"):
            return
 
        items = parsed.get("items", "").strip()
        total = parsed.get("total", "").strip()
 
        # Skip empty or invalid extractions
        if not items or not total or total == "0" or items == "...":
            print(f"⚠ Skipping empty order log for {phone}")
            return
 
        # Deduplicate — don't log the same order twice in a row
        last_log = getattr(detect_and_log_order, "_last_log", {})
        order_key = f"{phone}:{items}:{total}"
        if last_log.get("key") == order_key:
            print(f"⚠ Duplicate order skipped for {phone}")
            return
        detect_and_log_order._last_log = {"key": order_key}
 
        status = "COMPLAINT" if parsed.get("is_complaint") else "New"
 
        log_order(
            phone=phone,
            order_items=items,
            total=f"KES {total}",
            order_type=parsed.get("order_type", "Unknown"),
            raw_message=raw_message,
            status=status,
            location=parsed.get("location", "Not specified"),  # ← NEW
        )
 
    except json.JSONDecodeError:
        print(f"⚠ Order detection returned invalid JSON for {phone}")
    except Exception as e:
        print(f"⚠ Order detection error for {phone}: {e}")
 

# ── 5. ROUTES ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    print("Starting Zidi Kitchen Bot...")
    setup_sheet_headers()
    print("✓ Bot ready")


@app.get("/")
def health_check():
    return {
        "status": "online",
        "bot": "Zidi Kitchen",
        "tagline": "Kenyan Food. Done Right.",
    }


@app.post("/webhook/whatsapp")
async def reply(From: str = Form(...), Body: str = Form(...)):
    phone = From.replace("whatsapp:", "").strip()
    message = Body.strip()

    # Handle completely empty messages
    if not message:
        twiml = MessagingResponse()
        twiml.message("Samahani, sijapokea ujumbe wako. Tafadhali jaribu tena 😊")
        return Response(content=str(twiml), media_type="application/xml")

    try:
        save_to_history(phone, "user", message)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *get_history(phone),
            ],
            max_tokens=500,
            temperature=0.7,
        )

        ai_msg = response.choices[0].message.content
        save_to_history(phone, "assistant", ai_msg)

        # Log order in background — never blocks the customer reply
        detect_and_log_order(phone, get_history(phone), message)

    except Exception as e:
        print(f"❌ Error for {phone}: {e}")
        # Clear history so next message starts fresh
        conversation_memory[phone] = []
        ai_msg = (
            "Pole sana! Zidi experienced a small hitch 🙏\n\n"
            "Please try again — or call us directly: +254 701 234 567"
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
                "phone": phone,
                "messages": len(history),
                "last": history[-1]["content"][:60] + "..." if history else "",
            }
            for phone, history in conversation_memory.items()
        ],
    }