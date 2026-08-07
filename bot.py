import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# زيادة الـ Workers لضمان معالجة الاتصالات بأعلى كفاءة
app = Client(
    "my_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    workers=16
)

# متغيّرات الحالة
is_cancelled = False
pending_links = {} 

# لوحة الزر الشفاف للإلغاء
cancel_markup = InlineKeyboardMarkup([
    [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_process")]
])

def cleanup_and_kill():
    os.system("pkill -f aria2c")
    os.system("pkill -f 7z")
    if os.path.exists('input_file'):
        try: os.remove('input_file')
        except: pass
    for f in os.listdir('.'):
        if f.startswith('part.7z.'):
            try: os.remove(f)
            except: pass

async def process_splitting(client, message, url):
    global is_cancelled
    is_cancelled = False
    try:
        # === المرحلة 1: التنزيل ===
        msg_download = await message.reply_text(
            "📡 **المرحلة [1/3]: بدء التنزيل**\n\n"
            "⏳ جاري جلب الملف بأقصى سرعة عبر (Aria2 x16)...",
            reply_markup=cancel_markup
        )
        process = await asyncio.create_subprocess_shell(
            f'aria2c -x 16 -s 16 -k 1M --summary-interval=5 "{url}" -o input_file'
        )
        while process.returncode is None:
            if is_cancelled: 
                process.kill()
                cleanup_and_kill()
                return
            await asyncio.sleep(1)
            
        try: await msg_download.delete()
        except: pass
        await message.reply_text("✅ **انتهت مرحلة التنزيل بنجاح!**")

        # === المرحلة 2: التجزئة ===
        msg_split = await message.reply_text(
            "✂️ **المرحلة [2/3]: معالجة الملف والتجزئة**\n\n"
            "⚙️ جاري تقسيم الملف لأجزاء بحجم **1 جيجابايت** بنمط القص الفائق بدون ضغط...",
            reply_markup=cancel_markup
        )
        process7z = await asyncio.create_subprocess_shell('7z a -v1000m -mx0 part.7z input_file')
        while process7z.returncode is None:
            if is_cancelled: 
                process7z.kill()
                cleanup_and_kill()
                return
            await asyncio.sleep(1)

        if os.path.exists('input_file'): 
            os.remove('input_file')

        try: await msg_split.delete()
        except: pass
        await message.reply_text("✅ **انتهت مرحلة تجزئة الملف بنجاح!**")

        # === المرحلة 3: الرفع (بدون تحديثات تقدم لمنع البطء) ===
        files = sorted([f for f in os.listdir('.') if f.startswith('part.7z.')])
        for f in files:
            if is_cancelled: 
                cleanup_and_kill()
                return
            
            status_msg = await message.reply_text(
                f"🚀 **المرحلة [3/3]: جاري رفع الجزء إلى تليجرام...**\n\n"
                f"📄 **الملف:** `{f}`\n\n"
                f"⚡ *تم تفعيل النمط السريع (خام) لضمان أقصى سرعة رفع ممكنة.*",
                reply_markup=cancel_markup
            )
            
            # الرفع المباشر بدون تمرير دالة progress لتوفير الموارد ومواضيع الاتصال
            await message.reply_document(document=f)
            
            try: await status_msg.delete()
            except: pass
            
            if os.path.exists(f): 
                os.remove(f)

        if not is_cancelled:
            await message.reply_text("🎉 **تمت العملية بنجاح!**\n\n✅ تم تنزيل وتجزئة ورفع جميع الأجزاء بنجاح وبأعلى سلامة للبيانات.")

    except Exception as e:
        cleanup_and_kill()
        if str(e) != "CANCELLED":
            await message.reply_text(f"❌ **حدث خطأ أثناء تنفيذ العملية:**\n`{str(e)}`")

@app.on_message(filters.command("split") & filters.private)
async def split_cmd(client, message):
    args = message.text.split()
    if len(args) > 1:
        await process_splitting(client, message, args[1])
    else:
        pending_links[message.chat.id] = True
        await message.reply_text("🔗 **أهلاً بك!**\n\nالرجاء إرسال رابط الملف الآن في رسالة مستقلة وسأبدأ المعالجة فوراً.\n\n💡 *ملاحظة: يمكنك الإلغاء في أي لحظة عبر الزر الشفاف.*")

@app.on_message(filters.text & filters.private & ~filters.command(["start", "split", "help"]))
async def text_handler(client, message):
    if pending_links.get(message.chat.id):
        pending_links[message.chat.id] = False
        await process_splitting(client, message, message.text)

@app.on_callback_query(filters.regex("cancel_process"))
async def cancel_callback(client, callback_query):
    global is_cancelled
    is_cancelled = True
    cleanup_and_kill()
    pending_links[callback_query.message.chat.id] = False
    await callback_query.message.edit_text("🚫 **تم إلغاء العملية بالكامل وتنظيف السيرفر!**\n\nيمكنك إرسال رابط جديد في أي وقت.")

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await message.reply_text("✨ **أهلاً بك في بوت التجزئة والرفع السريع!** 🤖\n\n📌 **طريقة البدء:** أرسل `/split` متبوعاً برابط الملف، أو اضغط `/split` وسأطلب منك الرابط.")

@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client, message):
    await message.reply_text("📖 **دليل الاستخدام:**\n\n1️⃣ أرسل `/split`.\n2️⃣ أرسل الرابط في رسالة مستقلة.\n3️⃣ البوت سيقوم بالتنزيل والتجزئة والرفع تلقائياً.")

async def handle(request): 
    return web.Response(text="Bot is alive!")

async def start_web_server():
    server = web.Application()
    server.router.add_get('/', handle)
    runner = web.AppRunner(server)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080))).start()

async def main():
    await start_web_server()
    await app.start()
    print("🚀 البوت يعمل الآن بالتحديث والتسلسل الجديد بأقصى أداء.")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
