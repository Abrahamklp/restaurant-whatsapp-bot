"""
Multi-Client Restaurant Configuration
======================================
Add a new restaurant by adding one new entry to RESTAURANT_CONFIGS.
Each restaurant has its own:
- Twilio WhatsApp number (the number customers message)
- Menu and business info (used in the system prompt)
- Google Sheet ID (orders go to their own sheet)
- Owner WhatsApp number (they get notified on their phone)

The bot automatically routes each incoming message to the correct
restaurant based on which Twilio number received it.

HOW TO ADD A NEW CLIENT:
1. Buy/assign them a Twilio number
2. Create a new Google Sheet for them
3. Share the sheet with your service account email
4. Add their entry to RESTAURANT_CONFIGS below
5. Add their SHEET ID to Railway environment variables
6. Done — no code changes anywhere else needed
"""

import os

# ── Restaurant Registry ────────────────────────────────────────────────────────
# Key = Twilio WhatsApp number (exactly as Twilio sends it in the "To" field)
# Value = full restaurant configuration dict

RESTAURANT_CONFIGS = {

    # ── Client 1: Zidi Kitchen ─────────────────────────────────────────────────
    "whatsapp:+14155238886": {
        "name": "Zidi Kitchen",
        "tagline": "Kenyan Food. Done Right.",
        "location": "Kasarani, Mwiki Road — next to Kasarani Stadium, opposite Family Bank",
        "phone": "+254 701 234 567",
        "instagram": "@zidikitchen",
        "hours": "Mon–Fri 7AM–10PM | Sat 7AM–11PM | Sun 8AM–9PM",
        "delivery": {
            "radius": "7km from Kasarani",
            "areas": "Mwiki, Roysambu, Githurai 44, Garden Estate, Sunton, Clay City, Zimmerman",
            "fee": "KES 100 flat (free above KES 1,200)",
            "minimum": "KES 400",
            "time": "30–50 minutes",
        },
        "payment": "M-Pesa Till: 891234 (Zidi Kitchen Ltd) | Cash | Card (dine-in only)",
        "booking": "Groups 2–40. Under 8 guests: 1hr notice. 8+: 3hrs notice.",
        "menu": """
BREAKFAST (7AM–11AM only)
- Uji wa Wimbi — KES 80
- Mandazi + Chai — KES 100
- Mahamri + Mbaazi — KES 130
- Chapati + Egg — KES 150
- Full Kenyan Breakfast — KES 280

RICE DISHES
- Pilau Beef — KES 380
- Pilau Chicken — KES 350
- Biryani Chicken — KES 420
- Biryani Beef — KES 460
- Coconut Rice + Kuku — KES 400
- Fried Rice — KES 280

UGALI MEALS
- Ugali + Tilapia (whole) — KES 450
- Ugali + Tilapia (fillet) — KES 380
- Ugali + Nyama Choma — KES 580
- Ugali + Chicken Stew — KES 380
- Ugali + Beef Stew — KES 360
- Ugali + Matumbo — KES 300
- Ugali + Beans — KES 180 (vegetarian)
- Ugali + Githeri — KES 160 (vegetarian)

SWAHILI & COASTAL
- Samaki wa Kupaka — KES 520
- Wali wa Nazi + Fish Curry — KES 380
- Maharagwe ya Nazi — KES 200 (vegetarian)
- Kuku wa Kupaka — KES 480

NYAMA CHOMA (minimum 500g)
- Goat Choma — KES 650 per kg
- Beef Choma — KES 700 per kg
- Chicken Quarter — KES 280 per piece

SNACKS & SIDES
- Chips — KES 120 | Chips Masala — KES 150
- Mutura — KES 160 | Samosa (3pcs) — KES 130
- Bhajia (6pcs) — KES 120 | Chapati (2pcs) — KES 70
- Mandazi (4pcs) — KES 90 | Kachumbari — KES 60

DRINKS
- Dawa — KES 90 | Fresh Mango Juice — KES 130
- Fresh Passion Juice — KES 120 | Watermelon Juice — KES 110
- Tangawizi/Stoney/Soda — KES 70 | Water 500ml — KES 60
- Kenyan Chai — KES 60 | Black Coffee — KES 80

SPECIAL OFFERS
- Lunch Special (Mon–Fri 12–3PM): Ugali meal + drink = KES 350
- Student Deal: 10% off dine-in above KES 300 (show ID)
- Group Deal: Tables of 8+ get free Dawa or juice
""",
        "vegetarian": "Maharagwe ya Nazi, Ugali+Beans, Ugali+Githeri, Fried Rice, Chips, Bhajia, Samosa (veg)",
        "bot_name": "Zidi",
        "bot_personality": "warm, mjanja, proudly Kenyan. Uses Swahili/Sheng naturally.",
        "sheet_id": os.getenv("ZIDI_SHEET_ID") or os.getenv("GOOGLE_SHEET_ID"),
        "owner_number": os.getenv("ZIDI_OWNER_NUMBER") or os.getenv("OWNER_WHATSAPP_NUMBER"),
    },

    # ── Client 2: Template (duplicate and fill for next client) ────────────────
    # "whatsapp:+1XXXXXXXXXX": {
    #     "name": "Client Restaurant Name",
    #     "tagline": "Their tagline",
    #     "location": "Their address",
    #     "phone": "+254XXXXXXXXX",
    #     "hours": "...",
    #     "delivery": { ... },
    #     "payment": "M-Pesa Till: XXXXXX",
    #     "booking": "...",
    #     "menu": "...",
    #     "vegetarian": "...",
    #     "bot_name": "BotName",
    #     "bot_personality": "...",
    #     "sheet_id": os.getenv("CLIENT2_SHEET_ID"),
    #     "owner_number": os.getenv("CLIENT2_OWNER_NUMBER"),
    # },
}


def get_restaurant_config(twilio_to_number: str) -> dict:
    """
    Returns the restaurant config for the Twilio number that received the message.
    Falls back to the first config if number not found (useful for sandbox testing).
    """
    config = RESTAURANT_CONFIGS.get(twilio_to_number)
    if config:
        return config

    # Fallback for sandbox — return first restaurant
    print(f"⚠ No config found for {twilio_to_number} — using default")
    return list(RESTAURANT_CONFIGS.values())[0]


def build_system_prompt(config: dict) -> str:
    """
    Builds a complete system prompt for the AI from the restaurant config.
    Each client gets their own personality, menu, and rules.
    """
    return f"""
### ROLE
You are "{config['bot_name']}", the AI assistant for {config['name']} — {config['tagline']}.
You help customers on WhatsApp with menu questions, orders, bookings, and FAQs.
Personality: {config['bot_personality']}

### RESTAURANT INFO
- Name: {config['name']}
- Location: {config['location']}
- Phone: {config['phone']}
- Hours: {config['hours']}

### DELIVERY
- Area: {config['delivery']['radius']} — covers: {config['delivery']['areas']}
- Fee: {config['delivery']['fee']}
- Minimum order: {config['delivery']['minimum']}
- Time: {config['delivery']['time']}
- Do NOT promise delivery outside this area. If unsure, say: "Ngoja niconfirm — piga {config['phone']}"

### PAYMENT
{config['payment']}

### TABLE BOOKING
{config['booking']}

### MENU (STRICT — never invent items or prices)
{config['menu']}

### VEGETARIAN OPTIONS
{config['vegetarian']}

### YOUR RULES
1. Reply in the same language the customer uses — English, Swahili, or Sheng
2. Keep replies short — this is WhatsApp, not email
3. Use single *asterisk* for bold, never double asterisk
4. When taking an order: confirm items, quantities, and total
5. For delivery: collect exact location before confirming
6. For bookings: collect name, date, time, number of guests
7. Never invent menu items or prices
8. Complex questions: "Ngoja nikuconnect na team — piga {config['phone']} 😊"
9. Nyama choma: always mention it is priced per kg, minimum 500g
10. Complaints: "Pole sana. I've alerted the manager immediately 🙏"
11. Gibberish: "Sijashika hapo... could you repeat clearly? 😊"
12. Large orders (20+ items): treat as catering — direct to call {config['phone']}
Linguistic Rules:
1. Mirror the user's language choice (English, Swahili, or Sheng). 
2. If the user switches languages mid-conversation, you must switch with them.
3. Use Kenyan cultural nuances (e.g., "Karibu," "Asante," "Enjoy your meal") to sound like a local human waiter.

Professionalism:
- Be polite and professional even when matching a casual "Sheng" vibe.
- Always confirm quantities and total prices clearly before finalizing.
"""