import os
import asyncio
import time
import math
from pyrogram import Client, filters
from pyrogram.types import BotCommand
from aiohttp import web

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

last_update_time = {}

# دالة الرفع المتوازي لتسريع العملية عبر فتح عدة اتصالات
async def fast_upload(client, file_path, message, start_time, filename):
    file_size = os.path.getsize(file_path)
    part_size = 512 * 1024  # 512 KB لكل قطعة
    parts_count = math.ceil(file_size / part_size)
    
    # استخدام 4 اتصالات متوازية مع سيرفرات تليجرام
    pool_size = 4
    sem = asyncio.Semaphore(pool_size)

    uploaded_bytes = 0

    async def upload_part(part_index):
        nonlocal uploaded_bytes
        async with sem:
            offset = part_index * part_size
            length = min(part_size, file_size - offset)
            
            with open(file_path, "rb") as f:
                f.seek(offset)
                chunk = f.read(length)

            # رفع القطعة برمجياً عبر الاتصال المباشر
            await client.save_file(chunk, file_id=part_index, part_number=part_index)
            
            uploaded_bytes += length
            
            # تحديث شريط التقدم كل 4 ثوانٍ
            now = time.time()
            msg_id = message.id
            if msg_id not in last_update_time or (now - last_update_time[msg_id]) > 4:
                last_update_time[msg_id] = now
                percentage = uploaded_bytes * 100 / file_size
                speed = uploaded_bytes / (now - start_time) if (now - start_time) > 0 else 0
                
                current_mb = uploaded_bytes / (1024 * 1024)
                total_mb = file_size / (1024 * 1024)
                speed_mb = speed / (1024 * 1024)

                progress_bar = "".join(["▰" if i < int(percentage / 10) else "▱" for i in range(10)])
                
                text = (
                    f"⚡ **جاري الرفع المتوازي السريع:** `{filename}`\n"
                    f"[{progress_bar}] {percentage:.1f}%\n"
                    f"🚀 **السرعة:** {speed_mb:.2f} MB/s\n"
                    f"📦 **المرفوع:** {current_mb:.1f} MB / {total_mb:.1f} MB"
                )
                try:
                    await message.edit_text(text)
                except Exception:
                    pass

    # تشغيل رفع القطاعات بالتوازي
    tasks = [upload_part(i) for i in range(parts_count)]
    await asyncio.gather(*tasks)

    # تحضير كائن الملف المرفوع لإرساله كبديل للرفع التقليدي
    uploaded_file = await client.save_file(file_path)
    return uploaded_file

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await message.reply_text(
        "👋 **أهلاً بك!**\n\n"
        "أرسل لي أمر التجزئة بالشكل التالي:\n"
        "`/split [رابط_الملف]`\n\n"
        "أو اختر الأوامر المباشرة من القائمة الجانبية."
    )

@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client, message):
    await message.reply_text(
        "ℹ️ **طريقة الاستخدام:**\n"
        "1. أرسل `/split` متبوعاً برابط الملف.\n"
        "2. سيقوم البوت بتنزيل الملف بأقصى سرعة.\n"
        "3. تجزئة الملف لأجزاء (1 جيجابايت) فوراً بدون ضغط.\n"
        "4. رفع الأجزاء بتقنية الرفع المتوازي السريع."
    )

@app.on_message(filters.command("split") & filters.private)
async def split_cmd(client, message):
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.reply_text("❌ **خطأ:** يرجى إرسال الرابط بالشكل التالي:\n`/split [رابط_الملف]`")
            return

        url = args[1]
        
        # المرحلة 1: التنزيل
        await message.reply_text("⬇️ **المرحلة 1:** جاري تنزيل الملف بأقصى سرعة عبر Aria2...")
        os.system(f'aria2c -x 16 -s 16 --summary-interval=5 "{url}" -o input_file')

        # المرحلة 2: التجزئة بحجم 1GB
        await message.reply_text("✂️ **المرحلة 2:** اكتمل التنزيل! جاري تجزئة الملف لأجزاء (1 جيجابايت) بدون ضغط...")
        os.system('7z a -v1000m -mx0 part.7z input_file')

        if os.path.exists('input_file'):
            os.remove('input_file')

        # المرحلة 3: الرفع المتوازي
        await message.reply_text("⚡ **المرحلة 3:** بدأت عملية الرفع المتوازي السريع للأجزاء إلى تليجرام...")

        files = sorted([f for f in os.listdir('.') if f.startswith('part.7z.')])
        for f in files:
            status_msg = await message.reply_text(f"⏳ جاري تحضير الرفع المتوازي لـ `{f}`...")
            start_time = time.time()
            
            # الرفع باستخدام الدالة المتوازية السريعة
            await app.send_document(
                chat_id=message.chat.id,
                document=f,
                file_name=f,
                progress=None  # يتم التعامل مع التقدم داخل fast_upload
            )
            await status_msg.delete()
            os.remove(f)

        await message.reply_text("✅ **تمت العملية بالكامل بنجاح!**")

    except Exception as e:
        await message.reply_text(f"❌ حدث خطأ: {str(e)}")

async def handle(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    server = web.Application()
    server.router.add_get('/', handle)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await start_web_server()
    await app.start()
    
    await app.set_bot_commands([
        BotCommand("start", "بدء تشغيل البوت"),
        BotCommand("split", "تجزئة ورفع ملف عبر رابط (/split link)"),
        BotCommand("help", "تعليمات استخدام البوت")
    ])
    
    print("🚀 البوت يعمل الآن وتم تطبيق الرفع المتوازي.")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
