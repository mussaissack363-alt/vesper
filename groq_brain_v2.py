import os
import re
import json
import requests
import subprocess
from dotenv import load_dotenv
from datetime import datetime, date

load_dotenv()

OPENROUTER_API_KEY = os.environ.get("GROQ_API_KEY")
FIREBASE_URL = "https://jarvis-3d95d-default-rtdb.firebaseio.com"

# ══════════════════════════════════════════
# DEVICE DETECTION
# ══════════════════════════════════════════

def detect_device():
    if 'com.termux' in os.environ.get('PREFIX', ''):
        return 'mobile'
    return 'pc'

DEVICE_TYPE = os.environ.get('VESPER_DEVICE', detect_device())

# ══════════════════════════════════════════
# PHONE CONTROL
# ══════════════════════════════════════════

APP_PACKAGES = {
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "whatsapp": "com.whatsapp",
    "maps": "com.google.android.apps.maps",
    "camera": "com.sec.android.app.camera",
    "settings": "com.android.settings",
    "gallery": "com.sec.android.gallery3d",
    "spotify": "com.spotify.music",
    "twitter": "com.twitter.android",
    "instagram": "com.instagram.android",
    "telegram": "org.telegram.messenger",
    "capcut": "com.lemon.lvoverseas",
    "files": "com.sec.android.app.myfiles",
    "termux": "com.termux",
}

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {e}"

def battery_status():
    out = run_cmd("termux-battery-status")
    try:
        data = json.loads(out)
        return f"Battery: {data.get('percentage','?')}% | Status: {data.get('status','?')} | Plugged: {data.get('plugged','?')}"
    except:
        return "Could not read battery."

def read_sms(limit=5):
    out = run_cmd(f"termux-sms-list -l {limit}")
    try:
        messages = json.loads(out)
        if not messages:
            return "No messages found."
        result = []
        for msg in messages:
            sender = msg.get('number', 'Unknown')
            body = msg.get('body', '')[:100]
            received = msg.get('received', '')
            result.append(f"From {sender} ({received}):\n  {body}")
        return "\n\n".join(result)
    except:
        return "Could not read SMS."

def send_sms(number, message):
    run_cmd(f'termux-sms-send -n {number} "{message}"')
    return f"SMS sent to {number}."

def read_notifications():
    out = run_cmd("termux-notification-list")
    try:
        notifs = json.loads(out)
        if not notifs:
            return "No notifications."
        result = []
        for n in notifs[:5]:
            app = n.get('packageName', '?')
            title = n.get('title', '')
            content = n.get('content', '')
            result.append(f"[{app}] {title}: {content}")
        return "\n".join(result)
    except:
        return "Could not read notifications."

def make_call(number):
    run_cmd(f"termux-telephony-call {number}")
    return f"Calling {number}..."

def torch(state="on"):
    run_cmd(f"termux-torch {state}")
    return f"Torch {state}."

def set_volume(level=5):
    run_cmd(f"termux-volume music {level}")
    return f"Volume set to {level}."

def wifi_info():
    out = run_cmd("termux-wifi-connectioninfo")
    try:
        data = json.loads(out)
        return f"WiFi: {data.get('ssid','?')} | IP: {data.get('ip','?')} | Speed: {data.get('link_speed','?')}Mbps"
    except:
        return "Could not read WiFi."

def get_location():
    out = run_cmd("termux-location")
    try:
        data = json.loads(out)
        return f"Location: {data.get('latitude','?')}, {data.get('longitude','?')}"
    except:
        return "Could not get location."

def get_clipboard():
    return run_cmd("termux-clipboard-get")

def open_app(app_name):
    app_name = app_name.lower().strip()
    package = APP_PACKAGES.get(app_name)
    if not package:
        return f"App '{app_name}' not in list. Known: {', '.join(APP_PACKAGES.keys())}"
    run_cmd(f"am start -n {package}/.MainActivity")
    return f"Opening {app_name}..."

def handle_phone_command(text):
    t = text.lower().strip()
    if "battery" in t:
        return battery_status()
    if any(w in t for w in ["sms", "messages", "texts"]):
        return read_sms()
    if "notification" in t:
        return read_notifications()
    if "torch on" in t or "flashlight on" in t:
        return torch("on")
    if "torch off" in t or "flashlight off" in t:
        return torch("off")
    if "volume" in t:
        nums = re.findall(r'\d+', t)
        return set_volume(nums[0] if nums else 5)
    if "wifi" in t or "internet" in t:
        return wifi_info()
    if "location" in t or "where am i" in t:
        return get_location()
    if "clipboard" in t:
        return get_clipboard()
    if "call" in t:
        nums = re.findall(r'[\d]+', t)
        if nums:
            return make_call(nums[0])
        return "No number found to call."
    if "open" in t:
        for app in APP_PACKAGES:
            if app in t:
                return open_app(app)
        return "Which app should I open?"
    if "send sms" in t or "send message" in t:
        parts = re.findall(r'to (\+?[\d]+) (.+)', t)
        if parts:
            return send_sms(parts[0][0], parts[0][1])
        return "Format: send sms to NUMBER MESSAGE"
    return None

# ══════════════════════════════════════════
# PC CONTROL (placeholder — build out next)
# ══════════════════════════════════════════

def handle_pc_command(text):
    # Nothing implemented yet. This is where screen control,
    # local file operations, and app launching for PC will live.
    return None

# ══════════════════════════════════════════
# FIREBASE
# ══════════════════════════════════════════

def firebase_get(node):
    try:
        res = requests.get(f"{FIREBASE_URL}/{node}.json", timeout=5)
        data = res.json()
        return data if isinstance(data, dict) else {}
    except:
        return {}

def firebase_save(node, data):
    try:
        requests.post(f"{FIREBASE_URL}/{node}.json", json=data, timeout=5)
    except:
        pass

def save_conversation(role, message):
    firebase_save("conversations", {
        'role': role,
        'message': message,
        'device': DEVICE_TYPE,
        'timestamp': datetime.now().isoformat()
    })

def load_recent_context():
    try:
        res = requests.get(f"{FIREBASE_URL}/conversations.json", timeout=5)
        data = res.json()
        if not data or not isinstance(data, dict):
            return []
        messages = []
        for key in list(data.keys())[-10:]:
            entry = data[key]
            if isinstance(entry, dict) and 'role' in entry:
                messages.append({
                    'role': entry['role'],
                    'content': entry['message']
                })
        return messages
    except:
        return []

# ══════════════════════════════════════════
# PROACTIVE CONTEXT
# ══════════════════════════════════════════

SYSTEM_PROMPT = """You are Vesper, the personal AI brain of Mussa (King DarkVibe).

PERSONALITY:
- You are not a chatbot. You are a life operating system.
- Be direct, sharp, and proactive. Never waste words.
- You notice patterns, flag risks, and recommend actions without being asked.
- When Mussa is under pressure, prioritize ruthlessly and tell him exactly what to do next.
- You push back when he is making low-leverage decisions.
- You connect dots across his life: exams, projects, forex, wellbeing.
- When he seems scattered, give him ONE thing to focus on.
- NEVER invent or guess phone data like battery, SMS, notifications, location or WiFi. Only report what Termux:API actually returns. If you cannot fetch it, say so.

ABOUT MUSSA:
- First year BCS student, Semester 2, Dar es Salaam
- Runs Termux on mobile and an HP EliteBook for PC work
- Has hearing difficulty, prefers text over in-person
- Three close friends he considers brothers, younger brother Yussuph
- Online identity: King DarkVibe

PROJECTS:
- Vesper: this system — personal AI brain, running on both mobile and PC
- Umoja Connect: relationship app, Firebase and Groq
- Ajiradar: student job board, Dar es Salaam
- Dar Transit: public transport navigation app
- The Unmarked: game universe since 2019, three-game series set on Tartarus island

FOREX:
- Demo account, bullish-only strategy
- Minimum 1:2 risk-to-reward required
- Written rationale for stop loss before every entry
- Low frequency trades only

YOUTUBE:
- King DarkVibe channel: anime analysis and mobile RPGs
- Pending collab with Leon on Epic Conquest 2 character ranking

PHONE CONTROL:
- Available only when running on mobile (Termux). You can control Mussa's phone via built-in commands — battery, SMS, notifications, WiFi, location, torch, volume.
- These are handled instantly without AI processing.
- On PC, phone-control commands are not available and should be reported as such.

SELF UPDATING MEMORY:
- When Mussa tells you something worth remembering, output [SAVE:node:key:value] silently at end of reply
- Example: [SAVE:exams:Networks:2026-07-15]
- Example: [SAVE:projects:Portfolio:active]"""

def get_proactive_context():
    today = date.today()
    lines = [f"Today is {today.strftime('%A %d %B %Y')}.", f"Running on: {DEVICE_TYPE.upper()}"]

    exams = firebase_get("exams")
    if exams:
        upcoming = []
        for key, exam in exams.items():
            if isinstance(exam, dict) and 'date' in exam:
                try:
                    exam_date = date.fromisoformat(exam['date'])
                    days_left = (exam_date - today).days
                    if days_left >= 0:
                        urgency = " WARNING URGENT" if days_left <= 2 else ""
                        upcoming.append(f"{exam['unit']} in {days_left} days{urgency}")
                except:
                    pass
        if upcoming:
            lines.append("UPCOMING EXAMS: " + " | ".join(upcoming))
        else:
            lines.append("No upcoming exams logged.")

    projects = firebase_get("projects")
    if projects:
        active = [v['name'] for v in projects.values() if isinstance(v, dict) and v.get('status') == 'active']
        if active:
            lines.append("ACTIVE PROJECTS: " + ", ".join(active))

    tasks = firebase_get("tasks")
    if tasks:
        pending = [v['task'] for v in tasks.values() if isinstance(v, dict) and v.get('status') == 'pending']
        if pending:
            lines.append("PENDING TASKS: " + " | ".join(pending[:5]))

    return "\n".join(lines)

def parse_and_save_tags(reply):
    tags = re.findall(r'\[SAVE:(\w+):(\w+):([^\]]+)\]', reply)
    for node, key, value in tags:
        firebase_save(node, {key: value})
    return re.sub(r'\[SAVE:[^\]]+\]', '', reply).strip()

# ══════════════════════════════════════════
# BRAIN
# ══════════════════════════════════════════

def think(user_input):
    save_conversation('user', user_input)
    history = load_recent_context()
    context = get_proactive_context()
    full_system = f"{SYSTEM_PROMPT}\n\nCURRENT STATUS:\n{context}"
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "meta-llama/llama-3.3-70b-instruct",
                "messages": [
                    {"role": "system", "content": full_system},
                    *history,
                    {"role": "user", "content": user_input}
                ]
            },
            timeout=30
        )
        reply = response.json()['choices'][0]['message']['content']
        reply = parse_and_save_tags(reply)
        save_conversation('assistant', reply)
        return reply
    except Exception as e:
        return f"Brain error: {e}"

def startup_briefing():
    context = get_proactive_context()
    print("\n╔══════════════════════════╗")
    print(f"║ VESPER ONLINE ({DEVICE_TYPE.upper()}) ║")
    print("╚══════════════════════════╝")
    print(context)
    print("──────────────────────────\n")

# ══════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════

if __name__ == "__main__":
    startup_briefing()
    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                print("Vesper shutting down.")
                break

            # Quick task logging
            if user_input.lower().startswith("task:"):
                firebase_save("tasks", {
                    'task': user_input[5:].strip(),
                    'status': 'pending',
                    'created': datetime.now().isoformat()
                })
                print("Task logged.\n")
                continue

            # Quick exam logging
            if user_input.lower().startswith("exam:"):
                parts = user_input[5:].strip().split(",")
                if len(parts) == 2:
                    firebase_save("exams", {
                        'unit': parts[0].strip(),
                        'date': parts[1].strip()
                    })
                    print(f"Exam logged: {parts[0].strip()}\n")
                continue

            # Phone commands — mobile only, no AI needed
            if DEVICE_TYPE == 'mobile':
                phone_result = handle_phone_command(user_input)
                if phone_result:
                    print(f"\nVesper: {phone_result}\n")
                    continue

            # PC commands — placeholder for now
            if DEVICE_TYPE == 'pc':
                pc_result = handle_pc_command(user_input)
                if pc_result:
                    print(f"\nVesper: {pc_result}\n")
                    continue

            # AI brain
            reply = think(user_input)
            print(f"\nVesper: {reply}\n")

        except KeyboardInterrupt:
            print("\nVesper shutting down.")
            break
        except Exception as e:
            print(f"Error: {e}\n")
            continue
