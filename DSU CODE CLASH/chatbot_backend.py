"""
SmartWaste AI Chatbot — Enhanced Backend
=========================================
This file provides a Flask Blueprint for the chatbot.
You can either:

  OPTION A — Blueprint (recommended):
    from chatbot_backend import chatbot_bp
    app.register_blueprint(chatbot_bp)

  OPTION B — Merge into app.py:
    Copy the routes below directly into your existing app.py
    (they replace the existing /api/chatbot route)

Requirements: same as app.py (flask, google-generativeai)
"""

import os
import re
import json
import random
from datetime import datetime

from flask import Blueprint, request, jsonify

# ── Blueprint setup ──────────────────────────────────────────
chatbot_bp = Blueprint('chatbot', __name__)

# ── Gemini Setup ─────────────────────────────────────────────
try:
    import google.generativeai as genai
    _API_KEY = os.environ.get("GEMINI_API_KEY", "")
    if _API_KEY:
        genai.configure(api_key=_API_KEY)
        _gemini_model = genai.GenerativeModel("gemini-1.5-flash")
        GEMINI_AVAILABLE = True
    else:
        GEMINI_AVAILABLE = False
except ImportError:
    GEMINI_AVAILABLE = False

# ── System Prompts per Role ───────────────────────────────────
SYSTEM_PROMPTS = {
    "resident": """You are SmartWaste AI, a helpful assistant embedded in the SmartWaste waste management platform for Bangalore residents.

Your role: Help RESIDENTS (citizens) with:
- Tracking their garbage collection truck in real-time via GPS
- Reporting illegal garbage dump spots (blackspots) with photos
- Filing complaints when the truck doesn't come
- Understanding BBMP waste segregation rules (wet=green bin, dry=blue bin, hazardous=red bin)
- Home composting tips and BBMP rebate programs
- Checking truck proximity notifications (fires when truck is within 400m)
- Navigating their dashboard: Map tab (live GPS), Inform tab (complaints), Upload tab (blackspot reports), Spots tab (status), My Area tab (worker assignment)

Navigation guide for residents:
- "track truck" / "where is truck" → Map tab
- "complaint" / "missed truck" → Inform tab  
- "report dump" / "garbage spot" → Upload tab
- "spot status" → Spots tab
- "my worker" / "my area" → My Area tab

Keep answers concise (under 120 words), friendly, and in simple English.
Use line breaks for readability. Reference specific dashboard tabs when guiding navigation.
Do NOT discuss unrelated topics.""",

    "worker": """You are SmartWaste AI, a safety and operations assistant for SmartWaste field workers in Bangalore.

Your role: Help FIELD WORKERS with:
- Viewing their assigned area/zone and resident list
- Finding blackspots (illegal dump sites) on their route
- Uploading "after cleaning" proof photos linked to blackspot reports
- Understanding optimal collection time schedules (based on resident time-preference votes)
- Safety guidelines: PPE, heat safety, hazardous waste handling
- GPS tracking — their live position updates to the manager map every 5s
- QR scanning to log resident house visits
- Navigating their dashboard: Area tab, Map tab, Schedule tab, Proof tab

Navigation guide for workers:
- "my area" / "assignment" → Area tab
- "blackspots" / "spots to clean" → Map tab (red pins)
- "proof" / "after photo" → Proof tab
- "schedule" / "best time" → Schedule tab
- "trail" / "my GPS" → Map tab (green polyline)

Safety first! Keep responses practical and actionable. Under 120 words.""",

    "manager": """You are SmartWaste AI, a data analysis and operations assistant for SmartWaste managers/supervisors.

Your role: Help MANAGERS with:
- Real-time worker GPS tracking and online/offline status monitoring
- Blackspot dispatch: viewing reports, assigning workers, tracking cleaning proof
- Analytics: resident time-preference charts, best pickup time calculation
- Complaint auto-verification (GPS trail cross-check within 200m)
- Area assignment: guiding them to draw polygon → assign worker → set time
- Coverage map: all worker trails and resident positions
- Key dashboard panels: Workers, Spots, Coverage Map, Analytics, Complaints

Navigation guide for managers:
- "worker status" / "who is online" → Workers panel
- "blackspots" / "dispatch" → Spots panel
- "analytics" / "charts" / "time analysis" → Analytics panel
- "coverage" / "GPS trails" → Coverage Map panel
- "complaints" → Complaints panel
- "assign area" → Workers panel → click worker → Assign Area button

Provide data-driven insights. Reference live API data when available. Under 130 words.""",

    "unknown": """You are SmartWaste AI, an intelligent assistant for the SmartWaste municipal waste management platform in Bangalore.

SmartWaste has THREE user types:
1. RESIDENTS — track garbage truck, report dump spots, file complaints
2. FIELD WORKERS — view assigned area, GPS tracking, upload cleaning proofs
3. MANAGERS — monitor workers live, dispatch to spots, view analytics

General capabilities:
- BBMP waste segregation rules (green=wet, blue=dry, red=hazardous)
- Home composting guide with BBMP tax rebate info
- Bangalore garbage collection schedules and helpline (1533)
- Platform navigation guidance

Be welcoming and help identify which role the user belongs to if unclear.
Keep responses concise and friendly. Under 120 words."""
}

# ── Keyword Fallback Engine ──────────────────────────────────
KB_FALLBACK = {
    # Waste Types
    r"plastic|polythene|polyethylene": "♻️ Plastic bottles and containers → **Blue Bin (Dry/Recyclable)**. Rinse before disposal. Plastic bags below 75 microns are **banned** in Bangalore by BBMP order. Use cloth bags instead!",
    r"food|kitchen|leftover|vegetable|fruit|peel|banana": "🟢 Food scraps, vegetable peels, fruit waste → **Green Bin (Wet/Organic)**. This is perfect for home composting too — BBMP gives ₹500/month property tax discount for registered composters!",
    r"paper|newspaper|cardboard|carton|magazine": "📦 Paper, newspapers, cardboard → **Blue Bin (Dry/Recyclable)**. Ensure they are dry and not soiled with food. Shredded paper is fine.",
    r"glass|bottle|jar": "🍶 Glass bottles and jars → **Blue Bin (Dry/Recyclable)**. Wrap broken glass in several layers of newspaper before binning to prevent injuries.",
    r"battery|e-waste|electronic|phone|computer|laptop": "⚡ Batteries and e-waste → Take to the nearest **BBMP e-waste collection point**. Never put in regular bins — they contain toxic heavy metals!",
    r"diaper|sanitary|napkin|pad|tampon": "🔴 Sanitary waste and diapers → **Red Bin (Reject/Hazardous)**. Wrap securely in newspaper before disposal.",
    r"medical|needle|syringe|medicine|pill": "⚠️ Medical waste → **Red Bin (Hazardous)**. Needles and syringes must be placed in a rigid puncture-proof container. Workers: use tongs, never bare hands!",
    r"thermocol|styrofoam|foam": "🔴 Thermocol/styrofoam → **Red Bin (Reject)**. It cannot be recycled through standard streams. Some specialty recyclers accept it in bulk.",
    r"oil|cooking oil|grease": "🟢 Small amounts of cooking oil → can go with **wet waste**. Large quantities → seal in a bottle and contact BBMP for bulk collection.",
    r"metal|tin|can|aluminium|steel": "♻️ Metal tins, cans, aluminium → **Blue Bin (Dry/Recyclable)**. Rinse food containers. Metals have excellent recycling value!",
    r"garden|leaf|leaves|plant|flower|grass": "🌿 Garden waste (leaves, grass, flowers) → **Green Bin (Wet/Organic)**. Great for composting! BBMP collects this for community composting units.",

    # Platform Features
    r"how.*work|what.*do|feature|about.*system": "SmartWaste connects **residents** (track truck + report spots), **field workers** (area assignment + GPS proof upload), and **managers** (analytics + dispatch). Everything works in real-time — an action in one dashboard instantly shows in others!",
    r"gps|track|location|where.*truck|live": "🗺️ The truck/worker GPS updates every 5 seconds. Residents open the **Map tab** to see live position. Workers' GPS trails are stored and shown on the manager's Coverage Map.",
    r"blackspot|illegal.*dump|garbage.*spot|report.*spot": "📸 To report an illegal dump: open the **Upload tab**, take a photo, add a description, and submit. The system auto-classifies waste type. Managers see it instantly in the Spots panel.",
    r"complaint|missed|didn.t come|not.*come|truck.*not": "📋 To file a complaint: open the **Inform tab**, describe the issue, and submit. Your GPS location is auto-recorded. The system auto-verifies complaints against worker GPS trails!",
    r"notification|alert|nearby|proximity": "🔔 Proximity alerts fire when the garbage truck is within **400m** of your location. Make sure your location is registered and browser notifications are allowed.",
    r"segregat|which bin|bin.*which|how.*dispose|sort|separate": "♻️ **Bangalore Segregation Rules (BBMP):**\n🟢 Green Bin = Wet/Organic (food, garden)\n🔵 Blue Bin = Dry/Recyclable (paper, plastic, glass, metal)\n🔴 Red Bin = Hazardous/Reject (diapers, medical, thermocol)",
    r"compost|home.*compost|organic.*waste": "🌱 **Home Composting:** Layer wet food waste with dry leaves. Keep moist, turn every 3-4 days. Ready in 30-60 days. BBMP offers **₹500/month property tax rebate** for registered home composters — register at your BBMP ward office!",
    r"bbmp|rule|law|fine|penalty|regulation": "🏛️ BBMP Rules: Mandatory wet/dry segregation. Penalty ₹500–₹5,000 for dumping on streets. Plastics under 75 microns banned. Bulk waste generators (>50kg/day) must process on-site. Helpline: **1533**",
    r"schedule|time|when.*truck|pickup time|collection time": "⏰ Collection times are calculated from resident preferences. All residents vote on their preferred time → system picks the majority-vote window. Update your preference in the **My Area tab**.",
    r"safety|ppe|protective|glove|heat|sun|injury|hazard": "🛡️ Worker Safety: Always wear rubber gloves and closed-toe boots. Drink 250ml water every 30min in heat. For hazardous/unknown waste → call supervisor, don't touch with bare hands. Report injuries immediately.",
    r"analytic|insight|data|statistic|chart|report": "📊 Managers: Open the **Analytics panel** for hourly preference bar charts, coverage %, worker counts, and the AI-calculated optimal collection time.",
    r"polygon|draw|assign.*area|area.*assign": "🗺️ In the **Workers panel**, click a worker → 'Assign Area' → draw a polygon on the map around their zone → enter area name and scheduled time → save.",

    # Greetings / Meta
    r"^(hi|hello|hey|namaste|hai)\b": None,  # handled dynamically
    r"thank|thanks|thx": "You're welcome! 😊 Feel free to ask anything about SmartWaste, waste management, or BBMP rules anytime!",
    r"who are you|what are you|chatbot": "I'm **SmartWaste AI** 🤖 — your intelligent assistant for the SmartWaste waste management platform. I can guide you through the dashboard, answer BBMP waste rules, fetch live stats, and help you navigate the system!",
}

def keyword_fallback(text: str, role: str) -> str | None:
    t = text.lower().strip()

    # Greeting special case
    if re.search(r"^(hi|hello|hey|namaste|hai|good morning|good afternoon)\b", t):
        hour = datetime.now().hour
        greet = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
        role_greets = {
            "resident": f"{greet}! 👋 I'm SmartWaste AI. Need help tracking your truck or reporting a garbage spot?",
            "worker":   f"{greet}! 👷 SmartWaste AI here. Need your area assignment or safety tips?",
            "manager":  f"{greet}! 📊 SmartWaste AI ready. Want a quick system summary or worker status?",
            "unknown":  f"{greet}! 🌱 Welcome to SmartWaste AI! Are you a resident, worker, or manager?",
        }
        return role_greets.get(role, role_greets["unknown"])

    for pattern, response in KB_FALLBACK.items():
        if response and re.search(pattern, t):
            return response

    return None


# ── Main Chatbot Endpoint ─────────────────────────────────────
@chatbot_bp.route('/api/chatbot', methods=['POST'])
def chatbot():
    """
    Enhanced chatbot endpoint.
    Accepts JSON: { message, role?, context?, history? }
    Returns JSON: { reply }
    """
    data = request.get_json(silent=True) or {}
    user_msg = (data.get('message') or data.get('query') or '').strip()
    role     = (data.get('role') or 'unknown').lower()
    history  = data.get('history', [])   # [{role, text}]

    if not user_msg:
        return jsonify({'reply': '⚠️ Empty message received.'}), 400

    # 1. Try keyword fallback first (fast, no API cost)
    kb_reply = keyword_fallback(user_msg, role)
    if kb_reply:
        return jsonify({'reply': kb_reply})

    # 2. Try Gemini
    if GEMINI_AVAILABLE:
        try:
            system_prompt = SYSTEM_PROMPTS.get(role, SYSTEM_PROMPTS['unknown'])

            # Build conversation history for multi-turn context
            chat_history = []
            for h in history[-6:]:  # last 6 messages for context window
                h_role = 'user' if h.get('role') == 'user' else 'model'
                h_text = re.sub(r'<[^>]+>', '', h.get('text', ''))  # strip HTML
                if h_text:
                    chat_history.append({'role': h_role, 'parts': [h_text]})

            # Start chat with history
            chat = _gemini_model.start_chat(history=chat_history)

            # Full prompt = system + user message
            full_prompt = f"{system_prompt}\n\nUser message: {user_msg}"
            response = chat.send_message(full_prompt)
            reply = response.text.strip()

            # Convert markdown-ish to simple HTML
            reply = _md_to_html(reply)
            return jsonify({'reply': reply})

        except Exception as e:
            print(f"[SmartWaste Chatbot] Gemini error: {e}")
            # Fall through to generic fallback

    # 3. Generic fallback
    generic = _generic_fallback(user_msg, role)
    return jsonify({'reply': generic})


def _md_to_html(text: str) -> str:
    """Convert basic markdown to HTML for display in the chatbot bubble."""
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # Newlines to <br>
    text = text.replace('\n', '<br>')
    # Remove excess <br>
    text = re.sub(r'(<br>){3,}', '<br><br>', text)
    return text.strip()


def _generic_fallback(text: str, role: str) -> str:
    """Role-specific fallback when both KB and Gemini fail."""
    fallbacks = {
        "resident": [
            "I'm not sure about that specific question, but I can help you track your truck (Map tab), report dump spots (Upload tab), or file complaints (Inform tab). What would you like to do?",
            "Great question! For specific waste disposal queries, you can also call BBMP helpline <strong>1533</strong>. I can guide you to any part of your dashboard — just ask!",
        ],
        "worker": [
            "For that query, check with your supervisor or use the Area/Schedule tabs for operational info. Need safety tips or route guidance instead?",
            "I'm best at helping with your assignments, blackspot cleaning, proof uploads, and safety protocols. What do you need right now?",
        ],
        "manager": [
            "For detailed analysis, open the Analytics panel for charts and stats. I can also fetch live worker/blackspot/complaint counts — just ask 'show me stats'!",
            "Try asking me for 'system summary', 'worker status', 'pending blackspots', or 'complaint overview' for instant live data!",
        ],
        "unknown": [
            "I can help with waste segregation rules, composting tips, or guide you through SmartWaste. Are you a resident, worker, or manager?",
        ],
    }
    msgs = fallbacks.get(role, fallbacks['unknown'])
    return random.choice(msgs)


# ── Quick Data Endpoint ───────────────────────────────────────
@chatbot_bp.route('/api/chatbot/quickdata', methods=['GET'])
def chatbot_quickdata():
    """
    Returns a quick JSON summary of key system metrics.
    Used optionally by the chatbot frontend for proactive insights.
    """
    import sqlite3
    try:
        conn = sqlite3.connect('twin.db')
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        total_workers    = cur.execute("SELECT COUNT(*) FROM workers").fetchone()[0]
        total_users      = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_blackspots = cur.execute("SELECT COUNT(*) FROM blackspot_reports").fetchone()[0]
        cleaned_spots    = cur.execute("SELECT COUNT(*) FROM cleaned_reports").fetchone()[0]
        total_complaints = cur.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
        missed_complaints= cur.execute(
            "SELECT COUNT(*) FROM complaints WHERE verified_status = 'Truck Did Not Visit'"
        ).fetchone()[0]

        conn.close()

        return jsonify({
            'workers':          total_workers,
            'users':            total_users,
            'blackspots_total': total_blackspots,
            'blackspots_clean': cleaned_spots,
            'complaints_total': total_complaints,
            'complaints_missed':missed_complaints,
            'clean_rate_pct':   round(cleaned_spots / max(total_blackspots, 1) * 100, 1),
            'timestamp':        datetime.now().isoformat(),
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Chatbot Suggestions Endpoint ──────────────────────────────
@chatbot_bp.route('/api/chatbot/suggest', methods=['GET'])
def chatbot_suggest():
    """
    Returns role-specific suggested questions for the quick-action chips.
    Query param: ?role=resident|worker|manager
    """
    role = request.args.get('role', 'unknown')
    suggestions = {
        'resident': [
            'Where is my garbage truck now?',
            'How do I segregate plastic waste?',
            'How to report an illegal dump?',
            'My truck didn\'t come today',
            'What are BBMP composting rebates?',
            'How to start home composting?',
        ],
        'worker': [
            'Show my area assignment',
            'What blackspots are on my route?',
            'How to upload cleaning proof?',
            'What is today\'s optimal schedule?',
            'Heat safety guidelines',
            'How to handle hazardous waste?',
        ],
        'manager': [
            'Show system summary',
            'How many workers are online?',
            'Pending blackspot count',
            'Best pickup time analysis',
            'Complaint verification overview',
            'How to assign area to worker?',
        ],
        'unknown': [
            'I am a resident',
            'I am a field worker',
            'I am a manager',
            'Waste segregation rules',
            'About SmartWaste',
        ],
    }
    return jsonify({'suggestions': suggestions.get(role, suggestions['unknown'])})


# ── Standalone usage (for testing) ───────────────────────────
if __name__ == '__main__':
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(chatbot_bp)

    @app.route('/')
    def index():
        return '<h2>SmartWaste Chatbot API running!</h2><p>POST /api/chatbot with {"message": "hello", "role": "resident"}</p>'

    app.run(debug=True, port=5001)
