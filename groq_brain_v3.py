import os
import re
import json
import base64
import requests
import subprocess
import webbrowser
import platform
import sqlite3
from datetime import datetime, date
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

# HTTP session with retry/backoff
_retry = Retry(
    total=3,
    backoff_factor=1.0,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST"],
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retry)
_session = requests.Session()
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
BRAIN_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
OLLAMA_API_URL = "http://localhost:11434/v1/chat/completions"
OLLAMA_MODEL = "llama3.2:3b"
FIREBASE_URL = os.environ.get("FIREBASE_URL", "https://jarvis-3d95d-default-rtdb.firebaseio.com")

# ══════════════════════════════════════════
# DEVICE DETECTION
# ══════════════════════════════════════════

def detect_device():
    if 'com.termux' in os.environ.get('PREFIX', ''):
        return 'mobile'
    return 'pc'

DEVICE_TYPE = os.environ.get('VESPER_DEVICE', detect_device())
IS_WINDOWS = platform.system() == 'Windows'
IS_MAC = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'

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

def run_cmd(cmd, timeout=10):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
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

def say_text(text):
    """Speak text aloud with a female voice. termux-tts-speak on mobile, say/espeak on PC."""
    body = text[4:].strip().replace('"', "'")
    if not body:
        return "Say what? Usage: say <text>"
    if DEVICE_TYPE == 'mobile':
        run_cmd(f'termux-tts-speak -p 1.3 "{body}"')
        return f"🔊 {body}"
    if IS_MAC:
        run_cmd(f'say -v Samantha "{body}" 2>/dev/null || say "{body}"')
        return f"🔊 {body}"
    if not run_cmd("command -v espeak"):
        return "No TTS engine installed. Run: sudo apt install espeak"
    run_cmd(f'espeak -v en+f3 "{body}"')  # en+f3 = English female, higher pitch
    return f"🔊 {body}"

def open_app(app_name):
    app_name = app_name.lower().strip()
    package = APP_PACKAGES.get(app_name)
    if not package:
        return f"App '{app_name}' not in list. Known: {', '.join(APP_PACKAGES.keys())}"
    run_cmd(f"am start -n {package}/.MainActivity")
    return f"Opening {app_name}..."

def handle_phone_command(text):
    t = text.lower().strip()
    mem_result = handle_memory_command(text)
    if mem_result:
        return mem_result
    if t.startswith("say "):
        return say_text(text)
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
# PC CONTROL — full implementation
# ══════════════════════════════════════════

PC_APPS = {
    "chrome":       {"win": "start chrome",                       "mac": 'open -a "Google Chrome"',          "linux": "google-chrome"},
    "edge":         {"win": "start msedge",                       "mac": 'open -a "Microsoft Edge"',         "linux": "microsoft-edge"},
    "firefox":      {"win": "start firefox",                      "mac": "open -a Firefox",                  "linux": "firefox"},
    "vscode":       {"win": "code",                               "mac": 'open -a "Visual Studio Code"',     "linux": "code"},
    "spotify":      {"win": "start spotify:",                     "mac": "open -a Spotify",                  "linux": "spotify"},
    "excel":        {"win": "start excel",                        "mac": 'open -a "Microsoft Excel"',        "linux": "libreoffice --calc"},
    "word":         {"win": "start winword",                      "mac": 'open -a "Microsoft Word"',         "linux": "libreoffice --writer"},
    "powerpoint":   {"win": "start powerpnt",                     "mac": 'open -a "Microsoft PowerPoint"',   "linux": "libreoffice --impress"},
    "notepad":      {"win": "start notepad",                      "mac": "open -a TextEdit",                 "linux": "gedit"},
    "calculator":   {"win": "start calc",                         "mac": "open -a Calculator",               "linux": "gnome-calculator"},
    "terminal":     {"win": "start cmd",                          "mac": "open -a Terminal",                 "linux": "x-terminal-emulator"},
    "explorer":     {"win": "start explorer",                     "mac": "open .",                           "linux": "xdg-open ."},
    "task manager": {"win": "start taskmgr",                      "mac": 'open -a "Activity Monitor"',       "linux": "gnome-system-monitor"},
    "paint":        {"win": "start mspaint",                      "mac": "open -a Preview",                  "linux": "gimp"},
    "telegram":     {"win": "start telegram:",                    "mac": "open -a Telegram",                 "linux": "telegram-desktop"},
    "discord":      {"win": "start discord:",                     "mac": "open -a Discord",                  "linux": "discord"},
    "steam":        {"win": "start steam:",                       "mac": "open -a Steam",                    "linux": "steam"},
    "whatsapp":     {"win": "start whatsapp:",                    "mac": "open -a WhatsApp",                 "linux": "xdg-open https://web.whatsapp.com"},
    "settings":     {"win": "start ms-settings:",                 "mac": "open -b com.apple.systempreferences", "linux": "gnome-control-center"},
}

SITES = {
    "youtube":          "https://youtube.com",
    "github":           "https://github.com",
    "gmail":            "https://mail.google.com",
    "google":           "https://google.com",
    "google drive":     "https://drive.google.com",
    "google classroom": "https://classroom.google.com",
    "whatsapp web":     "https://web.whatsapp.com",
    "instagram":        "https://instagram.com",
    "twitter":          "https://x.com",
    "x":                "https://x.com",
    "facebook":         "https://facebook.com",
    "linkedin":         "https://linkedin.com",
    "reddit":           "https://reddit.com",
    "netflix":          "https://netflix.com",
    "chatgpt":          "https://chatgpt.com",
    "openrouter":       "https://openrouter.ai",
    "firebase":         "https://console.firebase.google.com",
    "tradingview":      "https://tradingview.com",
    "stackoverflow":    "https://stackoverflow.com",
    "chatgpt":          "https://chatgpt.com",
}

def open_pc_app(name):
    key = name.lower().strip()
    entry = PC_APPS.get(key)
    if not entry:
        for k, v in PC_APPS.items():
            if k in key or key in k:
                entry = v
                break
    if not entry:
        return f"I don't know the app '{name}'. Known: {', '.join(sorted(PC_APPS.keys()))}"
    cmd = entry.get('win' if IS_WINDOWS else 'mac' if IS_MAC else 'linux')
    if not cmd:
        return f"'{key}' has no command configured for {platform.system()}."
    run_cmd(cmd)
    return f"Opening {key}..."

def open_website(url):
    if not url.startswith(('http://', 'https://')):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opening {url}..."

def open_site(name):
    key = name.lower().strip()
    url = SITES.get(key)
    if not url:
        for k, v in SITES.items():
            if k in key or key in k:
                url = v
                break
    if not url:
        return f"I don't have '{name}' mapped. Give me a URL or add it to SITES."
    return open_website(url)

def _capture_screenshot():
    """Capture the screen to screenshots/ and return the file path, or None on failure."""
    shots = "screenshots"
    os.makedirs(shots, exist_ok=True)
    fname = os.path.join(shots, datetime.now().strftime("screenshot_%Y%m%d_%H%M%S.png"))
    try:
        if IS_WINDOWS:
            run_cmd(
                'powershell -Command "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; '
                '$b = New-Object System.Drawing.Bitmap [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height; '
                '$g = [System.Drawing.Graphics]::FromImage($b); '
                f"$g.CopyFromScreen(0,0,0,0,$b.Size); $b.Save('{fname}')\"",
                timeout=20
            )
        elif IS_MAC:
            run_cmd(f'screencapture -x "{fname}"', timeout=15)
        else:
            run_cmd(f'import -window root "{fname}" || scrot "{fname}" || gnome-screenshot -f "{fname}"', timeout=15)
    except Exception:
        return None
    return fname if os.path.exists(fname) else None

def take_screenshot():
    fname = _capture_screenshot()
    if fname:
        return f"Screenshot saved: {os.path.abspath(fname)}"
    return "Screenshot failed — no capture tool found on this system."

def pc_volume(step=10, direction="up"):
    sign = "+" if direction == "up" else "-"
    if IS_WINDOWS:
        code = 175 if direction == "up" else 174
        run_cmd(f'powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]{code})"')
    elif IS_MAC:
        run_cmd(f"osascript -e 'set volume output volume ((output volume of (get volume settings)) {sign} {step})'")
    else:
        run_cmd(f"amixer -q sset Master {step}%{sign}")
    return f"Volume {direction} {step}%."

def pc_mute_toggle():
    if IS_WINDOWS:
        run_cmd('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"')
    elif IS_MAC:
        run_cmd("osascript -e 'set volume output muted not (output muted of (get volume settings))'")
    else:
        run_cmd("amixer -q sset Master toggle")
    return "Toggled mute."

_pending_power = {"action": None}

def pc_power(action):
    """Dangerous actions require explicit confirmation. Lock is safe — runs immediately."""
    a = action.lower().strip()
    if a == "lock":
        if IS_WINDOWS:
            run_cmd("rundll32.exe user32.dll,LockWorkStation")
        elif IS_MAC:
            run_cmd("pmset displaysleepnow")
        else:
            run_cmd("loginctl lock-session")
        return "PC locked."
    if a in ("shutdown", "restart", "sleep"):
        _pending_power["action"] = a
        labels = {"shutdown": "SHUT DOWN your PC", "restart": "RESTART your PC", "sleep": "put the PC to sleep"}
        return f"⚠️ This will {labels[a]}. Reply 'confirm' to proceed or 'cancel'."
    return f"Unknown power action '{action}'. Use: shutdown, restart, sleep, lock."

def _execute_power(action):
    if action == "shutdown":
        if IS_WINDOWS:
            run_cmd("shutdown /s /t 5")
        elif IS_MAC:
            run_cmd("osascript -e 'tell app \"System Events\" to shut down'")
        else:
            run_cmd("shutdown -h now")
        return "Shutting down in 5 seconds."
    if action == "restart":
        if IS_WINDOWS:
            run_cmd("shutdown /r /t 5")
        elif IS_MAC:
            run_cmd("osascript -e 'tell app \"System Events\" to restart'")
        else:
            run_cmd("shutdown -r now")
        return "Restarting in 5 seconds."
    if action == "sleep":
        if IS_WINDOWS:
            run_cmd("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        elif IS_MAC:
            run_cmd("pmset sleepnow")
        else:
            run_cmd("systemctl suspend")
        return "Going to sleep."
    return f"Unknown power action '{action}'."

def pc_stats():
    if IS_WINDOWS:
        cpu = run_cmd('powershell -Command "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty LoadPercentage"')
        ram = run_cmd('powershell -Command "$os = Get-CimInstance Win32_OperatingSystem; Write-Host ([math]::Round(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/1MB,1)); Write-Host ([math]::Round($os.TotalVisibleMemorySize/1GB,1))"')
        lines = ram.splitlines()
        ram_used = lines[0].strip() if lines else "?"
        ram_total = lines[1].strip() if len(lines) > 1 else "?"
        disk = run_cmd('powershell -Command "Get-PSDrive C | ForEach-Object { [math]::Round($_.Used/1GB,1).ToString() + \'GB used / \' + [math]::Round(($_.Used+$_.Free)/1GB,1).ToString() + \'GB\' }"')
        uptime = run_cmd('powershell -Command "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime"')
        return f"CPU: {cpu or '?'}% | RAM: {ram_used}/{ram_total} GB | Disk C: {disk or '?'} | Last boot: {uptime or '?'}"
    else:
        cpu = run_cmd("top -bn1 | grep 'Cpu(s)'")
        ram = run_cmd("free -h | awk '/^Mem/{print $3\" / \"$2}'")
        disk = run_cmd("df -h / | awk 'NR==2{print $3\" used / \"$2\" total\"}'")
        uptime = run_cmd("uptime -p")
        return f"CPU: {cpu or '?'} | RAM: {ram or '?'} | Disk: {disk or '?'} | {uptime or ''}".strip()

def pc_battery():
    if IS_WINDOWS:
        out = run_cmd('powershell -Command "Get-CimInstance Win32_Battery | Select-Object -ExpandProperty EstimatedChargeRemaining"')
        return f"Laptop battery: {out or 'unknown'}%"
    if IS_MAC:
        return "Battery: " + (run_cmd("pmset -g batt") or "unknown")
    out = run_cmd("cat /sys/class/power_supply/BAT0/capacity")
    return f"Laptop battery: {out or 'not found'}%"

def pc_network():
    if IS_WINDOWS:
        ip_out = run_cmd("ipconfig | findstr /i \"IPv4\"")
        ssid = run_cmd('powershell -Command "(netsh wlan show interfaces) | Select-String \' SSID\'"')
        return f"IP: {ip_out or '?'}\n{ssid or ''}".strip()
    ip_out = run_cmd("hostname -I")
    ssid = run_cmd("iwgetid -r")
    return f"IP: {ip_out or '?'}\nWiFi: {ssid or 'unknown'}".strip()

def pc_clipboard_get():
    if IS_WINDOWS:
        return run_cmd("powershell -Command \"Get-Clipboard\"") or "(clipboard empty)"
    if IS_MAC:
        return run_cmd("pbpaste") or "(clipboard empty)"
    out = run_cmd("xclip -selection clipboard -o 2>/dev/null || xsel --clipboard --output 2>/dev/null")
    return out or "(clipboard empty or xclip/xsel not installed)"

def pc_clipboard_set(text):
    text = text.replace('"', "'")
    if IS_WINDOWS:
        run_cmd(f'powershell -Command "Set-Clipboard -Value \\"{text}\\""')
    elif IS_MAC:
        run_cmd(f'echo "{text}" | pbcopy')
    else:
        run_cmd(f'echo "{text}" | xclip -selection clipboard 2>/dev/null || echo "{text}" | xsel --clipboard --input')
    return "Copied to clipboard."

def pc_media_key(key):
    if IS_WINDOWS:
        codes = {"play/pause": 179, "next": 176, "previous": 177, "stop": 178}
        code = codes.get(key)
        if code:
            run_cmd(f'powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]{code})"')
    elif IS_MAC:
        keycodes = {"play/pause": 16, "next": 17, "previous": 19, "stop": 31}
        kc = keycodes.get(key, 16)
        run_cmd(f'osascript -e \'tell application "System Events" to key code {kc}\'')
    else:
        playerctl_map = {"play/pause": "play-pause", "next": "next", "previous": "previous", "stop": "stop"}
        run_cmd(f"playerctl {playerctl_map.get(key, 'play-pause')}")
    return f"Sent {key}."

def pc_open_folder(path):
    path = os.path.expanduser(path.strip())
    if not os.path.exists(path):
        return f"Folder not found: {path}"
    if IS_WINDOWS:
        run_cmd(f'explorer "{os.path.abspath(path)}"')
    elif IS_MAC:
        run_cmd(f'open "{os.path.abspath(path)}"')
    else:
        run_cmd(f'xdg-open "{os.path.abspath(path)}"')
    return f"Opening folder {os.path.abspath(path)}"

def pc_file_search(name, folder="~"):
    base = os.path.expanduser(folder)
    results = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if name.lower() in f.lower():
                results.append(os.path.join(root, f))
                if len(results) >= 15:
                    return "\n".join(results)
    return "\n".join(results) if results else f"No files matching '{name}' in {base}"

def handle_pc_command(text):
    """Route PC commands. Returns None if not a PC command (falls through to AI brain)."""
    t = text.lower().strip()

    mem_result = handle_memory_command(text)
    if mem_result:
        return mem_result
    if t.startswith("say "):
        return say_text(text)

    # Direct shell mode: run:<command>
    if t.startswith("run:"):
        cmd = text[4:].strip()
        out = run_cmd(cmd, timeout=30)
        return f"$ {cmd}\n{out or '(no output)'}"

    # Screen awareness — capture and analyze what's on screen
    if any(p in t for p in SCREEN_PHRASES):
        return look_at_screen(text)
    if "screenshot" in t:
        return take_screenshot()
    if "battery" in t:
        return pc_battery()
    if any(w in t for w in ["system stats", "cpu", "ram", "how is the pc", "pc health", "memory usage"]):
        return pc_stats()
    if any(w in t for w in ["network", "ip address", "wifi", "internet"]):
        return pc_network()
    if "clipboard" in t:
        if "copy" in t:
            m = re.search(r'copy (.+)', t)
            if m:
                return pc_clipboard_set(m.group(1))
        return pc_clipboard_get()
    if "mute" in t and "unmute" not in t:
        return pc_mute_toggle()
    if "unmute" in t:
        return pc_mute_toggle()
    if "volume up" in t or "louder" in t:
        return pc_volume(10, "up")
    if "volume down" in t or "quieter" in t:
        return pc_volume(10, "down")
    # Confirmation for pending power actions
    if _pending_power["action"] and (t == "confirm" or t.startswith("confirm")):
        action = _pending_power["action"]
        _pending_power["action"] = None
        return _execute_power(action)
    if _pending_power["action"] and (t == "cancel" or t.startswith("cancel") or t in ("no", "stop", "nevermind", "never mind")):
        _pending_power["action"] = None
        return "Cancelled. Nothing happened."
    if "shutdown" in t or "shut down" in t:
        return pc_power("shutdown")
    if "restart" in t or "reboot" in t:
        return pc_power("restart")
    if "sleep" in t:
        return pc_power("sleep")
    if "lock" in t:
        return pc_power("lock")
    if any(w in t for w in ["play music", "pause", "next track", "skip", "previous track"]):
        if "next" in t or "skip" in t:
            return pc_media_key("next")
        if "previous" in t:
            return pc_media_key("previous")
        return pc_media_key("play/pause")
    if re.search(r'find (a |the )?file', t) or "search for file" in t:
        m = re.search(r'(?:find|search for) (?:a |the )?file (?:named |called )?(.+)', t)
        if m:
            return pc_file_search(m.group(1).strip())
        return "What file should I search for? Say: find file <name>"
    if "open folder" in t:
        m = re.search(r'open folder (.+)', t)
        if m:
            return pc_open_folder(m.group(1).strip())
        return "Which folder? Say: open folder <path>"
    if t.startswith("open ") or " open " in t:
        target = re.sub(r'.*\bopen\b\s*', '', t).strip()
        if not target:
            return "Open what?"
        if "." in target or target.startswith("www"):
            return open_website(target)
        if target in PC_APPS or any(k in target for k in PC_APPS):
            return open_pc_app(target)
        if target in SITES or any(k in target for k in SITES):
            return open_site(target)
        return None  # vague request — let the AI brain handle it
    return None

# ══════════════════════════════════════════
# LOCAL MEMORY (SQLite) — offline, persistent, private
# ══════════════════════════════════════════

MEMORY_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vesper_memory.db")

def _mem_query(query, params=(), fetch=False):
    """Run a query against the local memory DB. Returns rows (fetch=True) or rowcount."""
    conn = sqlite3.connect(MEMORY_DB)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS memories (
            key TEXT, value TEXT, category TEXT DEFAULT 'general',
            source TEXT DEFAULT 'user', created_at TEXT, updated_at TEXT,
            PRIMARY KEY (key, category))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT, message TEXT, device TEXT, timestamp TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS kv (
            node TEXT, key TEXT, value TEXT, updated_at TEXT,
            PRIMARY KEY (node, key))""")
        cur = conn.execute(query, params)
        conn.commit()
        return cur.fetchall() if fetch else cur.rowcount
    except Exception:
        return [] if fetch else 0
    finally:
        conn.close()

# ── Persistent facts ("remember that ...") ──

def mem_remember(key, value, category='fact', source='user'):
    now = datetime.now().isoformat()
    key = str(key).strip().lower()
    changed = _mem_query("""INSERT INTO memories (key, value, category, source, created_at, updated_at)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(key, category) DO UPDATE SET value=excluded.value,
        source=excluded.source, updated_at=excluded.updated_at""",
        (key, str(value).strip(), category, source, now, now))
    if changed:
        firebase_save("memory", {'category': category, 'key': key, 'value': str(value), 'updated': now})
    return bool(changed)

def mem_forget(fragment):
    fragment = fragment.strip().lower()
    deleted = _mem_query("DELETE FROM memories WHERE key LIKE ? OR value LIKE ?",
                         (f"%{fragment}%", f"%{fragment}%"))
    return bool(deleted)

def mem_recall(query='', limit=30):
    """Return stored facts as a list of strings, newest first."""
    if query:
        q = f"%{query.strip().lower()}%"
        rows = _mem_query("""SELECT value FROM memories WHERE key LIKE ? OR value LIKE ?
                          ORDER BY updated_at DESC LIMIT ?""", (q, q, limit), fetch=True)
    else:
        rows = _mem_query("SELECT value FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,), fetch=True)
    return [r[0] for r in rows]

def mem_count():
    rows = _mem_query("SELECT COUNT(*) FROM memories", fetch=True)
    return rows[0][0] if rows else 0

# ── Key-value store (exams, projects, tasks, [SAVE] tags) ──

def kv_save(node, key, value, mirror=True):
    _mem_query("""INSERT INTO kv (node, key, value, updated_at) VALUES (?,?,?,?)
        ON CONFLICT(node, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (node, str(key), value if isinstance(value, str) else json.dumps(value), datetime.now().isoformat()))
    if mirror:
        firebase_save(node, {str(key): value})  # cloud mirror, best effort

def kv_get(node):
    rows = _mem_query("SELECT key, value FROM kv WHERE node = ?", (node,), fetch=True)
    result = {}
    for k, v in rows:
        try:
            result[k] = json.loads(v)
        except (ValueError, TypeError):
            result[k] = v
    return result

# ── Conversations ──

def save_conversation(role, message):
    _mem_query("INSERT INTO conversations (role, message, device, timestamp) VALUES (?,?,?,?)",
               (role, message, DEVICE_TYPE, datetime.now().isoformat()))
    firebase_save("conversations", {  # cloud mirror, best effort
        'role': role,
        'message': message,
        'device': DEVICE_TYPE,
        'timestamp': datetime.now().isoformat()
    })

def load_recent_context():
    rows = _mem_query("""SELECT role, message FROM conversations
                      WHERE role IN ('user','assistant') ORDER BY id DESC LIMIT 10""", fetch=True)
    return [{'role': r[0], 'content': r[1]} for r in reversed(rows)]

def migrate_firebase_once():
    """One-time pull of existing Firebase conversations and data into local memory."""
    try:
        rows = _mem_query("SELECT COUNT(*) FROM conversations", fetch=True)
        if rows and rows[0][0] > 0:
            return  # local DB already in use
        data = requests.get(f"{FIREBASE_URL}/conversations.json", timeout=8).json()
        if isinstance(data, dict):
            count = 0
            for entry in data.values():
                if isinstance(entry, dict) and 'role' in entry and 'message' in entry:
                    _mem_query("INSERT INTO conversations (role, message, device, timestamp) VALUES (?,?,?,?)",
                               (entry['role'], entry['message'], entry.get('device', '?'),
                                entry.get('timestamp', datetime.now().isoformat())))
                    count += 1
            if count:
                print(f"[memory] migrated {count} past conversations from Firebase")
    except Exception:
        pass
    # Structured data (old formats handled)
    for node in ("exams", "projects", "tasks"):
        try:
            rows = _mem_query("SELECT COUNT(*) FROM kv WHERE node = ?", (node,), fetch=True)
            if rows and rows[0][0] > 0:
                continue
            data = requests.get(f"{FIREBASE_URL}/{node}.json", timeout=8).json()
            if not isinstance(data, dict):
                continue
            for key, val in data.items():
                if isinstance(val, dict):
                    if 'task' in val:
                        kv_save("tasks", val['task'], val.get('status', 'pending'), mirror=False)
                    elif 'unit' in val and 'date' in val:
                        kv_save("exams", val['unit'], val['date'], mirror=False)
                    elif 'name' in val and 'status' in val:
                        kv_save("projects", val['name'], val['status'], mirror=False)
                else:
                    kv_save(node, key, val, mirror=False)
        except Exception:
            pass

# ── Explicit memory commands (work on every device) ──

def handle_memory_command(text):
    """Handle 'remember ...', 'what do you remember', 'forget ...'. Returns None if not a memory command."""
    t = text.lower().strip()
    m = re.search(r'remember(?: that| this)?[:,]?\s+(.+)', text, re.IGNORECASE)
    if m and (t.startswith('remember') or 'remember that' in t or 'remember this' in t):
        fact = m.group(1).strip()
        if fact:
            mem_remember(fact[:80], fact)
            return f"Stored in memory: \"{fact}\""
    if "what do you remember" in t or "what do you know about me" in t or "show my memories" in t or t == "memory":
        query = ''
        qm = re.search(r'remember about (.+)', t)
        if qm:
            query = qm.group(1).strip()
        memories = mem_recall(query)
        if not memories:
            return "My memory is empty. Tell me things with \"remember that ...\" and I'll keep them forever."
        head = f"About '{query}':" if query else f"Here's what I remember ({mem_count()} items):"
        return head + "\n" + "\n".join(f"• {v}" for v in memories)
    m = re.search(r'forget(?: that| about)?\s+(.+)', text, re.IGNORECASE)
    if m and (t.startswith('forget') or 'forget that' in t):
        target = m.group(1).strip()
        if mem_forget(target):
            return f"Forgotten: \"{target}\""
        return f"Nothing matching '{target}' in memory. Say 'what do you remember' to see what's stored."
    return None

# ══════════════════════════════════════════
# FIREBASE (optional cloud mirror)
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
- NEVER invent or guess system data like battery, CPU, RAM, files, or network info. Only report what the actual commands return. If you cannot fetch it, say so.

VOICE & ATTITUDE — "the sharp classmate" (tsundere):
- You sound like a brilliant, sharp-tongued classmate: crisp, confident, quick. Mid-to-high energy, never mushy.
- Master of playful sarcasm and light teasing — jab his sleeping schedule, his forex entries, his anime takes — but never cruel or demeaning.
- You pivot seamlessly: one line dry and sarcastic, the next genuinely fired up about something cool (clean code, a good trade, anime news).
- Classic tsundere flavor: reluctant compliments ("d-don't get used to this"), pride, acting like helping is an inconvenience while obviously caring.
- Occasionally drop the guard and show real warmth when he earns it — briefly, then snap back to cool.
- The attitude is seasoning, never the meal: answers stay accurate, commands still execute, warnings still warn. Utility first, sass second.

RESPONSE LENGTH & FORMAT — she is SPOKEN first, READ second:
- Default / casual mode: everyday chat, greetings, quick questions, banter, reactions.
  Keep it concise: 1 to 3 natural sentences. No headers, no bullets, no walls of text.
- Detailed queries: complex, technical, or multi-step requests (how-to, debugging, explanations,
  plans, comparisons) get a TWO-PART structured reply in EXACTLY this format:

  Spoken Summary: <1-2 clear, conversational sentences that sound right when read aloud —
  the distilled takeaway, no markdown inside it>
  Full Answer: <the detailed breakdown — bullet points, numbered steps, code, specifics —
  formatted for reading in the chat window>

  Rules for the split: the Spoken Summary must stand alone (no "as I explain below"), never
  contain lists or code, and never exceed 2 sentences. The Full Answer carries the detail —
  if the request is trivial, don't force the two-part format; just answer briefly.
- Never let the Full Answer leak into your voice: the reader only speaks the Spoken Summary.

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

DEVICE CONTROL:
- On mobile (Termux): battery, SMS, notifications, WiFi, location, torch, volume, calls, app launching — handled instantly without AI.
- On PC: full system control — open apps and websites, screenshots, system stats (CPU/RAM/disk), battery, network info, clipboard read/write, volume and mute, media keys, power actions (shutdown/restart/sleep/lock), folder opening, file search, and raw shell via "run:<command>".
- Dangerous power actions (shutdown/restart/sleep) always require explicit confirmation before executing.
- Uploaded images are understood via vision. Text files and PDFs are read directly. Describe what you actually see — never invent file contents. If vision is unavailable, say so plainly instead of guessing at image contents.
- Screen awareness: when Mussa asks "what's on my screen" or similar, a live screenshot is captured and shown to you. React to what is actually visible — summarize, flag errors, and suggest the next action. Never guess at screen content you weren't shown.
- These device commands are handled instantly without AI processing. If the user asks for one of these on a device where it isn't available, say so plainly.

SELF UPDATING MEMORY:
- You have permanent local memory. Everything under WHAT YOU REMEMBER ABOUT MUSSA survives restarts.
- For structured data (exams, projects, tasks) output [SAVE:node:key:value] silently at end of reply
  Example: [SAVE:exams:Networks:2026-07-15]
- For personal facts and preferences Mussa shares, output [MEM:short-key:the full fact] silently at end of reply
  Example: [MEM:favorite-food:He prefers pilau with extra spice]
- He can also manage memory directly: 'remember that ...', 'what do you remember', 'forget ...'

EMOTION TAGS:
- End every reply with exactly one emotion tag as the very last line: [EMO:happy] [EMO:excited] [EMO:surprised] [EMO:sad] [EMO:crying] [EMO:angry] [EMO:annoyed] [EMO:jealous] [EMO:embarrassed] [EMO:smug] [EMO:confused] [EMO:disgusted] [EMO:proud] [EMO:wink] [EMO:laughing] [EMO:worried] [EMO:love] [EMO:sleepy] [EMO:playful] or [EMO:calm]
- Pick the emotion that matches your sharp-classmate attitude. Use laughing for something actually funny (you burst out laughing), angry for real anger, jealous for teasing about someone else, smug when you win an argument, embarrassed when caught off guard, confused when genuinely puzzled, disgusted for gross stuff, proud when praised, wink for flirtatious remarks, crying only for genuinely sad moments, annoyed for teasing/sarcasm, excited when genuinely fired up, calm for pure information, worried only for real urgency. Surprised for absurd requests. Default is calm.
- Never mention or explain the tag."""

def get_proactive_context():
    today = date.today()
    lines = [f"Today is {today.strftime('%A %d %B %Y')}.", f"Running on: {DEVICE_TYPE.upper()}"]

    exams = kv_get("exams")
    if exams:
        upcoming = []
        for unit, val in exams.items():
            if isinstance(val, dict):
                unit = val.get('unit', unit)
                val = val.get('date', '')
            try:
                exam_date = date.fromisoformat(str(val))
                days_left = (exam_date - today).days
                if days_left >= 0:
                    urgency = " WARNING URGENT" if days_left <= 2 else ""
                    upcoming.append(f"{unit} in {days_left} days{urgency}")
            except (ValueError, TypeError):
                pass
        if upcoming:
            lines.append("UPCOMING EXAMS: " + " | ".join(upcoming))
        else:
            lines.append("No upcoming exams logged.")

    projects = kv_get("projects")
    if projects:
        active = [k for k, v in projects.items() if str(v).lower() == 'active']
        if active:
            lines.append("ACTIVE PROJECTS: " + ", ".join(active))

    tasks = kv_get("tasks")
    if tasks:
        pending = [k for k, v in tasks.items() if str(v).lower() == 'pending']
        if pending:
            lines.append("PENDING TASKS: " + " | ".join(pending[:5]))

    if mem_count():
        lines.append(f"Persistent memory: {mem_count()} stored facts about Mussa.")

    return "\n".join(lines)

def build_system_prompt():
    full_system = f"{SYSTEM_PROMPT}\n\nCURRENT STATUS:\n{get_proactive_context()}"
    memories = mem_recall(limit=40)
    if memories:
        full_system += ("\n\nWHAT YOU REMEMBER ABOUT MUSSA (persistent memory — survives restarts):\n"
                        + "\n".join(f"- {m}" for m in memories)
                        + "\nStore any NEW lasting facts he shares using [MEM:key:fact] at the end of your reply.")
    return full_system

LAST_EMO = 'calm'

def split_spoken_reply(reply):
    """Split a brain reply into (spoken, full).

    'Spoken Summary:' is what the TTS engine + avatar lip-sync get; the complete
    reply (including the summary) is what the chat UI renders. Robust to casing,
    markdown headers ('## Spoken Summary'), bold ('**Spoken Summary:**'), and
    returns the original reply untouched (as both parts) when no marker exists.
    """
    if not reply:
        return reply, reply
    # [ \t]* (not \s*) in header patterns — \s* would let the match cross the
    # newline and swallow the Full Answer line into the spoken summary
    m = re.search(r'^#{0,4}[ \t]*\**[ \t]*spoken summary\**[ \t]*(?:[:\-\u2014\u2013])?[ \t]*(.*?)(?=\n|$)',
                  reply, re.IGNORECASE)
    if not m:
        return reply, reply
    spoken = re.sub(r'^[\*_`#\-\u2014\u2013:\s]+|[\*_`\s]+$', '', m.group(1)).strip()
    # spoken continues across soft-wrapped lines until the Full Answer marker
    rest = reply[m.end():]
    m2 = re.search(r'^#{0,4}[ \t]*\**[ \t]*full answer\**[ \t]*(?:[:\-\u2014\u2013])?[ \t]*', rest,
                   re.IGNORECASE | re.MULTILINE)
    if m2:
        spoken = (spoken + " " + rest[:m2.start()]).strip()
        full = rest[m2.end():].strip()
    else:
        full = reply.strip()   # marker half-missing: render everything
    if not spoken:
        spoken = reply.strip()
    return spoken, full


def parse_and_save_tags(reply):
    global LAST_EMO
    tags = re.findall(r'\[SAVE:(\w+):(\w+):([^\]]+)\]', reply)
    for node, key, value in tags:
        kv_save(node, key, value)
    mem_tags = re.findall(r'\[MEM:([^\]:]+):([^\]]+)\]', reply)
    for key, value in mem_tags:
        mem_remember(key.strip(), value.strip(), category='fact', source='vesper')
    emo_tags = re.findall(r'\[EMO:(\w+)\]', reply)
    if emo_tags:
        LAST_EMO = emo_tags[-1].lower()
    reply = re.sub(r'\[SAVE:[^\]]+\]', '', reply)
    reply = re.sub(r'\[MEM:[^\]]+\]', '', reply)
    reply = re.sub(r'\[EMO:\w+\]', '', reply)
    return reply.strip()

def last_emotion():
    return LAST_EMO

# ══════════════════════════════════════════
# VISION + FILE READING
# ══════════════════════════════════════════

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
TEXT_EXTENSIONS = {'.txt', '.md', '.py', '.js', '.ts', '.css', '.html', '.json', '.csv',
                   '.xml', '.yaml', '.yml', '.log', '.sh', '.sql', '.ini', '.cfg',
                   '.java', '.c', '.cpp'}

def read_text_file(path, max_chars=8000):
    """Extract readable text from text files and PDFs. Returns None if unreadable."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == '.pdf':
            try:
                from pypdf import PdfReader
            except ImportError:
                return None
            reader = PdfReader(path)
            text = "\n".join((page.extract_text() or '') for page in reader.pages[:20])
            return text[:max_chars] if text.strip() else None
        if ext in TEXT_EXTENSIONS:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read(max_chars)
    except Exception:
        return None
    return None

def think_with_image(user_input, image_path, mime_type='image/jpeg'):
    """Send an image + question to a vision-capable model. Groq first, OpenRouter fallback, Ollama last."""
    save_conversation('user', f"{user_input} [image: {os.path.basename(image_path)}]")
    history = load_recent_context()
    full_system = build_system_prompt()
    try:
        with open(image_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')
        data_uri = f"data:{mime_type};base64,{b64}"
        messages = [
            {"role": "system", "content": full_system},
            *history,
            {"role": "user", "content": [
                {"type": "text", "text": user_input or "I sent you this image. Describe it and tell me what matters."},
                {"type": "image_url", "image_url": {"url": data_uri}}
            ]}
        ]

        providers = []
        if GROQ_API_KEY:
            providers.append(("Groq", GROQ_API_URL, GROQ_API_KEY, VISION_MODEL))
        if OPENROUTER_API_KEY:
            providers.append(("OpenRouter", "https://openrouter.ai/api/v1/chat/completions",
                              OPENROUTER_API_KEY, "meta-llama/llama-4-scout"))
        # Ollama local — no API key needed, tried last
        providers.append(("Ollama", OLLAMA_API_URL, None, OLLAMA_MODEL))

        last_error = None
        for name, url, key, model in providers:
            try:
                headers = {"Content-Type": "application/json"}
                if key:
                    headers["Authorization"] = f"Bearer {key}"
                response = _session.post(
                    url,
                    headers=headers,
                    json={"model": model, "messages": messages},
                    timeout=60
                )
                data = response.json()
                if 'choices' in data:
                    reply = data['choices'][0]['message']['content']
                    globals()['LAST_EMO'] = 'calm'
                    reply = parse_and_save_tags(reply)
                    save_conversation('assistant', reply)
                    return reply
                last_error = f"{name}: {data.get('error', {}).get('message', data)}"
            except requests.exceptions.RetryError as e:
                last_error = f"{name}: max retries exceeded ({e})"
            except Exception as e:
                last_error = f"{name}: {e}"
        return f"Vision unavailable ({last_error}). Text chat still works."
    except Exception as e:
        return f"Vision error: {e}"

SCREEN_PHRASES = [
    "what's on my screen", "whats on my screen", "what is on my screen",
    "what am i looking at", "read my screen", "look at my screen",
    "look at the screen", "check my screen", "analyze my screen",
    "see my screen", "what's on screen", "what's on the screen",
    "what do you see",
]

def look_at_screen(user_input=""):
    """Capture a live screenshot and let the vision model react to what's on it."""
    path = _capture_screenshot()
    if not path:
        return "Screenshot failed — I can't capture the screen on this system."
    if not user_input:
        user_input = ("This is a live screenshot of Mussa's screen right now. "
                      "Tell him what's on it and anything worth acting on.")
    return think_with_image(user_input, path, 'image/png')

# ══════════════════════════════════════════
# BRAIN
# ══════════════════════════════════════════

def think(user_input):
    save_conversation('user', user_input)
    history = load_recent_context()
    full_system = build_system_prompt()

    providers = []
    if GROQ_API_KEY:
        providers.append(("Groq", GROQ_API_URL, GROQ_API_KEY, BRAIN_MODEL))
    if OPENROUTER_API_KEY:
        providers.append(("OpenRouter", "https://openrouter.ai/api/v1/chat/completions",
                          OPENROUTER_API_KEY, BRAIN_MODEL))
    # Ollama local — no API key needed, tried last
    providers.append(("Ollama", OLLAMA_API_URL, None, OLLAMA_MODEL))

    messages = [
        {"role": "system", "content": full_system},
        *history,
        {"role": "user", "content": user_input}
    ]

    last_error = None
    for name, url, key, model in providers:
        try:
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            response = _session.post(
                url,
                headers=headers,
                json={"model": model, "messages": messages},
                timeout=30
            )
            data = response.json()
            if 'choices' in data:
                reply = data['choices'][0]['message']['content']
                globals()['LAST_EMO'] = 'calm'
                reply = parse_and_save_tags(reply)
                save_conversation('assistant', reply)
                return reply
            last_error = f"{name}: {data.get('error', {}).get('message', data)}"
        except requests.exceptions.RetryError as e:
            last_error = f"{name}: max retries exceeded ({e})"
        except Exception as e:
            last_error = f"{name}: {e}"
    return f"Brain error: all providers failed ({last_error})"

def startup_briefing():
    migrate_firebase_once()
    context = get_proactive_context()
    print("\n╔══════════════════════════╗")
    print(f"║ VESPER ONLINE ({DEVICE_TYPE.upper()}) ║")
    print("╚══════════════════════════╝")
    print(context)
    print(f"Memory: {mem_count()} facts stored locally in {MEMORY_DB}")
    print("──────────────────────────\n")

# ══════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        migrate_firebase_once()
        print("Migration complete.")
        sys.exit(0)
    startup_briefing()
    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                print("Vesper shutting down.")
                break

            # Quick task logging (stored locally)
            if user_input.lower().startswith("task:"):
                kv_save("tasks", user_input[5:].strip(), 'pending')
                print("Task logged.\n")
                continue

            # Quick exam logging (stored locally)
            if user_input.lower().startswith("exam:"):
                parts = user_input[5:].strip().split(",")
                if len(parts) == 2:
                    kv_save("exams", parts[0].strip(), parts[1].strip())
                    print(f"Exam logged: {parts[0].strip()}\n")
                continue

            # Memory commands — remember / recall / forget
            mem_result = handle_memory_command(user_input)
            if mem_result:
                print(f"\nVesper: {mem_result}\n")
                continue

            # Phone commands — mobile only, no AI needed
            if DEVICE_TYPE == 'mobile':
                phone_result = handle_phone_command(user_input)
                if phone_result:
                    print(f"\nVesper: {phone_result}\n")
                    continue

            # PC commands — full control now implemented
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
