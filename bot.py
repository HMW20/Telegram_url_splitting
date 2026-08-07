import os
import asyncio
import time
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

is_cancelled = False

def cleanup():
    os.system("pkill -f aria2c")
    os.system("pkill -f 7z")
    if os.path.exists('input_file'):
        try: os.remove('input_file')
        except: pass
    for f in os.listdir('.'):
        if f.startswith('part.7z.'):
            try: os.remove(f)
            except: pass

async def progress(current, total, message):
    # تقليل التحديثات لزيادة سرعة الرفع
    if current % (1024 * 1024 * 50) == 0:  # تحديث كل 50 ميجا فقط
        try:
            await message.edit_text(f"🚀 الرفع: {current * 100 / total:.1f}%")
        except: pass

async def process_splitting(client, message, url):
    global is_cancelled
    is_cancelled = False
    
    try:
        # === 1. التنزيل ===
        msg = await message.reply_text("📡 جاري التنزيل...")
        
        proc = await asyncio.create_subprocess_shell(
            f'aria2c -x 16 -s 16 "{url}" -o input_file',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()

        # فحص جودة الملف
        if not os.path.exists('input_file') or os.path.getsize('input_file') < 1024 * 1024:
            await msg.edit_text("❌ فشل التحميل (الملف تالف أو غير موجود).")
            cleanup()
            return

        # === 2. التجزئة ===
        await msg.edit_text("✂️ جاري التجزئة...")
        proc7z = await asyncio.create_subprocess_shell('7z a -v1000m -mx0 part.7z input_file')
        await proc7z.wait()
        
        if os.path.exists('input_file'): os.remove('input_file')

        # === 3. الرفع ===
        files = sorted([f for f in os.listdir('.') if f.startswith('part.7z.')])
        for f in files:
            if is_cancelled: break
            await msg.edit_text(f"📦 جاري رفع: {f}")
            await message.reply_document(f, progress=progress, progress_args=(message,))
            os.remove(f)

        if not is_cancelled:
            await msg.edit_text("✅ تمت العملية بنجاح.")

    except Exception as e:
        await message.reply_text(f"❌ خطأ: {e}")
    finally:
        cleanup()

@app.on_message(filters.command("split") & filters.private)
async def split_cmd(client, message):
    if len(message.command) > 1:
        await process_splitting(client, message, message.command[1])
    else:
        await message.reply_text("أرسل الرابط الآن.")

@app.on_callback_query(filters.regex("cancel_process"))
async def cancel_callback(client, callback_query):
    global is_cancelled
    is_cancelled = True
    cleanup()
    await callback_query.message.edit_text("🚫 تم الإلغاء.")

# === Web Server للمحافظة على نشاط البوت ===
async def start_web_server():
    app_web = web.Application()
    runner = web.AppRunner(app_web)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080))).start()

async def main():
    await start_web_server()
    await app.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
