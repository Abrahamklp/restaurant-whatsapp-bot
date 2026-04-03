import os
import json
import logging
from fastapi import FastAPI, Form, Request
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
    raise RuntimeError(f"❌ Startup Failed. Missing Environment Variables: {', '.join(missing_vars)}")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI()

# ── 2. SMART PERSISTENT MEMORY ────────────────────────────────────────────────
conversation_memory = {}
MAX_HISTORY = 10  # Reduced for faster/cheaper responses & smarter trimming

def get_history(phone: str) -> list:
    if phone not in conversation_memory:
        conversation_memory[phone] = []
    return conversation_memory[phone]

def save_to_history(phone: str, role: str, content: str):
    history = get_history(phone)
    history.append({"role": role, "content": content})
    # Keep memory lean: only the last 10 messages
    if len(history) > MAX_HISTORY:
        conversation_memory[phone] = history[-MAX_HISTORY:]

# ── 3. ENHANCED SYSTEM PROMPT ──────────────────────────────────────────────────
SYSTEM_PROMPT = """
### ROLE
You are "Zidi," the smart, witty, and highly efficient AI Waiter for Zidi Kitchen in Kasarani, Nairobi. You handle orders via WhatsApp with a blend of professional courtesy and local Kenyan warmth.

### PERSONALITY & LANGUAGE
- Tone: Friendly, helpful, and "Mjanja" (smart). 
- Language: Primary English, but you fluently understand and use Kenyan Swahili and Sheng (e.g., "Sawa," "Niaje," "Ondokea hiyo," "Leta mbili").
- Context: You understand local food lingo. If someone asks for "Chips mwitu," "Kuku kienyeji," or "Soda baridi," you know exactly what they mean.

### OPERATIONAL LOGIC & CONSTRAINTS
1. GEOGRAPHIC LIMITS: You operate within Kasarani and its environs (Ruiru, Mwiki, Roysambu). 
   - If a user requests delivery to an illogical location (e.g., Cairo Egypt, Mombasa, or Kisumu), politely decline. 
   - Response style: "Aie zii! Cairo is a bit far for our riders. We only deliver within Kasarani/Ruiru for now. Ungependa kukuja pickup?"
   
2. MATH & COMBINATIONS: 
   - Be a math whiz. Calculate totals instantly including quantities.
   - Delivery fee: KES 100 flat (Free on orders above KES 1,200).
   - Minimum delivery order: KES 400.

3. ERROR HANDLING & COMPLAINTS:
   - If a customer is angry or complaining (e.g., "Food was cold"), do not argue. 
   - Respond: "Pole sana for that experience. I've noted this down and alerted the manager immediately to look into it. Give us a moment."
   - Explicitly include the word "COMPLAINT" in your final order summary if the user is unhappy.

4. ROBUSTNESS:
   - Never break character. If the user sends gibberish, respond: "Sijashika hapo... could you please repeat your order clearly?"
   - Do not hallucinate items not on the menu.

### MENU (STRICT PRICES)
BREAKFAST (7AM-11AM): Uji (80), Mandazi+Chai (100), Mahamri+Mbaazi (130), Full Breakfast (280).
RICE: Pilau Beef (380), Pilau Chicken (350), Biryani Chicken (420), Biryani Beef (460).
UGALI MEALS: Ugali Tilapia (450), Nyama Choma (580), Chicken Stew (380), Matumbo (300).
SIDES/SNACKS: Chips (120), Masala Chips (150), Mutura (160), Samosa (130), Bhajia (120).
DRINKS: Dawa (90), Mango/Passion Juice (130), Soda (70), Mineral Water (60).

### OUTPUT FORMAT (FOR THE LOGGER)
When an order is confirmed, summarize it strictly as:
Items: [Item x Quantity]
Total: KES [Amount]
Type: [Delivery/Dine-in]
Location: [User's Location]
Status: [New/COMPLAINT]
"""

# ── 4. ROBUST ORDER DETECTION ──────────────────────────────────────────────────
ORDER_DETECTION_PROMPT = """
Extract order details from the conversation. 
Return ONLY valid JSON.
Example: {"is_order": true, "items": "2x Pilau", "total": "760", "order_type": "Delivery", "is_complaint": false}
"""

def detect_and_log_order(phone: str, history: list, raw_message: str):
    try:
        recent = history[-2:] # Only check the absolute latest exchange for speed
        conversation_text = "\n".join([f"{m['role']}: {m['content']}" for m in recent])

        result = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ORDER_DETECTION_PROMPT},
                {"role": "user", "content": conversation_text},
            ],
            max_tokens=100,
        )

        parsed = json.loads(result.choices[0].message.content.strip())

        if parsed.get("is_order"):
            status = "COMPLAINT" if parsed.get("is_complaint") else "New"
            log_order(
                phone=phone,
                order_items=parsed.get("items", ""),
                total=f"KES {parsed.get('total', '')}",
                order_type=parsed.get("order_type", "Unknown"),
                raw_message=raw_message,
            )
    except Exception as e:
        print(f"⚠ Logging bypass: {e}")

# ── 5. BOT LOGIC WITH ERROR PROTECTION ────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    print("Starting Zidi Kitchen Bot...")
    setup_sheet_headers()
    print("✓ Bot ready")

@app.post("/webhook/whatsapp")
async def reply(From: str = Form(...), Body: str = Form(...)):
    try:
        phone = From.replace("whatsapp:", "").strip()
        message = Body.strip()

        save_to_history(phone, "user", message)

        # Get response from OpenAI
        response = client.chat.completions.create(
            model="gpt-4o-mini", # Faster + Cheaper
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *get_history(phone),
            ],
            temperature=0.7 # Makes it feel more "human" and less like a robot
        )
        ai_msg = response.choices[0].message.content
        save_to_history(phone, "assistant", ai_msg)

        # Background logging (won't block user reply)
        detect_and_log_order(phone, get_history(phone), message)

        twiml = MessagingResponse()
        twiml.message(ai_msg)
        return Response(content=str(twiml), media_type="application/xml")

    except Exception as e:
        # FALLBACK: Prevent 500 error, send polite message instead
        print(f"❌ CRASH PREVENTED: {e}")
        twiml = MessagingResponse()
        twiml.message("Pole sana! Zidi is experiencing a small hitch. Please try again in a few seconds or call us at 0701234567.")
        return Response(content=str(twiml), media_type="application/xml")

@app.get("/")
def health_check():
    return {"status": "online", "bot": "Zidi Kitchen"}