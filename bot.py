import os
import asyncio
from pyrogram import Client, filters

# جلب البيانات من إعدادات السيرفر (Environment Variables)
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("split") & filters.private)
async def split_cmd(client, message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply_text("❌ الاستخدام: `/split [الرابط]`")
        return

    url = args[1]
    msg = await message.reply_text("⬇️ جاري التنزيل...")

    # التنزيل
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

print("🚀 البوت يعمل الآن.")
app.run()
