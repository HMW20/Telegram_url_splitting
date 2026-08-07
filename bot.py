import os
import asyncio
from pyrogram import Client, filters
from aiohttp import web

# جلب البيانات من إعدادات السيرفر
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("split") & filters.private)
async def split_cmd(client, message):
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.reply_text("❌ الاستخدام: `/split [الرابط]`")
            return

        url = args[1]
        msg = await message.reply_text("⬇️ جاري التنزيل...")

        os.system(f'aria2c -x 16 -s 16 "{url}" -o input_file')
        
        await msg.edit_text("✂️ جاري التجزئة...")
        os.system('7z a -v500m part.7z input_file')

        await msg.edit_text("⬆️ جاري الرفع...")

        files = sorted([f for f in os.listdir('.') if f.startswith('part.7z.')])
        for f in files:
            await message.reply_document(document=f)
            os.remove(f)

        if os.path.exists('input_file'):
            os.remove('input_file')
        
        await msg.edit_text("✅ تم الانتهاء بنجاح!")

    except Exception as e:
        await message.reply_text(f"❌ حدث خطأ: {str(e)}")

# سيرفر خفيف لإرضاء منصة Render المجانية
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
    print("🚀 البوت والسيرفر يعملان الآن.")
    await app.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
