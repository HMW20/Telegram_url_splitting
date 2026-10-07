import os
import asyncio
import time
import re
import shlex
from collections import deque
from urllib.parse import urlparse, unquote, unquote_plus
from html import unescape

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web, ClientSession, ClientTimeout


API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")


app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ============================================================
# إعدادات المشروع
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(BASE_DIR, "jobs")

os.makedirs(JOBS_DIR, exist_ok=True)

# ============================================================
# حد التقسيم وأنواع الملفات للرفع المباشر
# ============================================================

# أي ملف أصغر من 1000 MiB سيتم إرساله مباشرة بدون تقسيم.
DIRECT_UPLOAD_LIMIT = 1000 * 1024 * 1024

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v",
    ".mpeg", ".mpg", ".3gp", ".ts", ".m2ts", ".flv", ".wmv"
}

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"
}

AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga",
    ".opus", ".wma", ".alac", ".amr"
}


# ============================================================
# حالة البوت والطابور
# ============================================================

pending_links = {}
job_queue = deque()

active_user = None
queue_worker_task = None

last_update_time = {}


# ============================================================
# زر الإلغاء
# ============================================================

cancel_markup = InlineKeyboardMarkup([
    [
        InlineKeyboardButton(
            "❌ إلغاء العملية",
            callback_data="cancel_process"
        )
    ]
])


# ============================================================
# معرفة هل الرابط MediaFire
# ============================================================

def is_mediafire_url(url):

    try:

        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        if not hostname:
            return False

        return (
            hostname == "mediafire.com"
            or hostname.endswith(".mediafire.com")
        )

    except Exception:

        return False


# ============================================================
# استخراج اسم الملف من الرابط
# ============================================================

def filename_from_url(url):

    try:

        path = urlparse(url).path
        filename = os.path.basename(path)

        filename = unquote_plus(filename)
        filename = filename.strip()

        if filename:
            return filename

    except Exception:
        pass

    return "downloaded_file"


# ============================================================
# تنظيف اسم الملف
# ============================================================

def safe_filename(filename):

    filename = os.path.basename(filename)

    filename = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        filename
    )

    filename = filename.strip()

    if not filename:
        filename = "downloaded_file"

    return filename


# ============================================================
# إنشاء مجلد خاص بالطلب
# ============================================================

def create_job_dir(chat_id):

    timestamp = int(time.time() * 1000)

    job_dir = os.path.join(
        JOBS_DIR,
        f"{chat_id}_{timestamp}"
    )

    os.makedirs(job_dir, exist_ok=True)

    return job_dir


# ============================================================
# تنظيف مجلد الطلب
# ============================================================

def cleanup_job_dir(job_dir):

    if not job_dir:
        return

    try:

        if os.path.exists(job_dir):

            for filename in os.listdir(job_dir):

                path = os.path.join(
                    job_dir,
                    filename
                )

                try:

                    if os.path.isfile(path):
                        os.remove(path)

                except Exception:
                    pass

            try:

                os.rmdir(job_dir)

            except Exception:
                pass

    except Exception:
        pass


# ============================================================
# إيقاف عمليات aria2 و 7z
# ============================================================

def cleanup_processes():

    os.system("pkill -f aria2c")
    os.system("pkill -f 7z")


# ============================================================
# البحث عن الملف الذي تم تنزيله
# ============================================================

def find_downloaded_file(job_dir):

    if not os.path.exists(job_dir):
        return None

    files = []

    for filename in os.listdir(job_dir):

        path = os.path.join(
            job_dir,
            filename
        )

        if os.path.isfile(path):

            if filename.endswith(".aria2"):
                continue

            files.append(path)

    if not files:
        return None

    files.sort(
        key=lambda p: os.path.getsize(p),
        reverse=True
    )

    return files[0]


# ============================================================
# تحويل حجم aria2 إلى Bytes
# ============================================================

def size_to_bytes(value, unit):

    units = {
        "B": 1,
        "KiB": 1024,
        "MiB": 1024 ** 2,
        "GiB": 1024 ** 3,
        "TiB": 1024 ** 4
    }

    try:

        return float(value) * units.get(
            unit,
            1
        )

    except Exception:

        return 0


# ============================================================
# تحليل سطر تقدم aria2
# ============================================================

def parse_aria2_progress(line):

    pattern = (
        r'\[#\S+\s+'
        r'([\d.]+)(B|KiB|MiB|GiB|TiB)'
        r'/'
        r'([\d.]+)(B|KiB|MiB|GiB|TiB)'
        r'\((\d+)%\)'
        r'.*?'
        r'DL:([\d.]+)(B|KiB|MiB|GiB|TiB)'
        r'(?:.*?ETA:(\S+))?'
    )

    match = re.search(
        pattern,
        line
    )

    if not match:
        return None

    current_value = match.group(1)
    current_unit = match.group(2)

    total_value = match.group(3)
    total_unit = match.group(4)

    percentage = int(
        match.group(5)
    )

    speed_value = match.group(6)
    speed_unit = match.group(7)

    eta = match.group(8) or "..."

    current_bytes = size_to_bytes(
        current_value,
        current_unit
    )

    total_bytes = size_to_bytes(
        total_value,
        total_unit
    )

    speed_bytes = size_to_bytes(
        speed_value,
        speed_unit
    )

    return {
        "current": current_bytes,
        "total": total_bytes,
        "percentage": percentage,
        "speed": speed_bytes,
        "eta": eta
    }


# ============================================================
# تحديث رسالة تقدم التنزيل
# ============================================================

async def update_download_progress(
    message,
    filename,
    data
):

    if not data:
        return

    now = time.time()

    msg_id = message.id

    if (
        msg_id in last_update_time
        and now - last_update_time[msg_id] < 4
    ):
        return

    last_update_time[msg_id] = now

    percentage = data["percentage"]

    current_mb = data["current"] / (
        1024 * 1024
    )

    total_mb = data["total"] / (
        1024 * 1024
    )

    speed_mb = data["speed"] / (
        1024 * 1024
    )

    filled = int(
        percentage / 10
    )

    progress_bar = "".join(
        "▰" if i < filled else "▱"
        for i in range(10)
    )

    text = (
        "📥 **المرحلة [1/3]: تنزيل الملف**\n\n"
        f"📄 **الملف:** `{filename}`\n\n"
        f"[{progress_bar}] **{percentage}%**\n\n"
        f"📊 **الحجم:** `{current_mb:.1f} MB` / "
        f"`{total_mb:.1f} MB`\n"
        f"⚡ **السرعة:** `{speed_mb:.2f} MB/s`\n"
        f"⏱️ **المتبقي تقريبًا:** `{data['eta']}`"
    )

    try:

        await message.edit_text(
            text,
            reply_markup=cancel_markup
        )

    except Exception:
        pass


# ============================================================
# شريط تقدم الرفع
# ============================================================

async def progress(
    current,
    total,
    client,
    message,
    start_time,
    filename
):

    now = time.time()

    msg_id = message.id

    if (
        msg_id not in last_update_time
        or now - last_update_time[msg_id] > 4
    ):

        last_update_time[msg_id] = now

        percentage = (
            current * 100 / total
            if total
            else 0
        )

        elapsed = max(
            now - start_time,
            0.001
        )

        speed = current / elapsed

        current_mb = current / (
            1024 * 1024
        )

        total_mb = total / (
            1024 * 1024
        )

        speed_mb = speed / (
            1024 * 1024
        )

        progress_bar = "".join(
            "▰"
            if i < int(percentage / 10)
            else "▱"
            for i in range(10)
        )

        text = (
            "🚀 **جاري رفع الملف إلى تليجرام...**\n\n"
            f"📄 **الملف:** `{filename}`\n"
            f"[{progress_bar}] **{percentage:.1f}%**\n\n"
            f"⚡ **السرعة:** `{speed_mb:.2f} MB/s`\n"
            f"📊 **الحجم:** "
            f"`{current_mb:.1f} MB` / `{total_mb:.1f} MB`"
        )

        try:

            await message.edit_text(
                text,
                reply_markup=cancel_markup
            )

        except Exception:
            pass


# ============================================================
# تنفيذ aria2 مع قراءة التقدم
# ============================================================

async def run_aria2_with_progress(
    cmd,
    message,
    expected_filename
):

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    while True:

        line = await process.stdout.readline()

        if not line:
            break

        try:

            text = line.decode(
                errors="ignore"
            ).strip()

        except Exception:

            text = ""

        if text:

            print(text)

            progress_data = parse_aria2_progress(
                text
            )

            if progress_data:

                await update_download_progress(
                    message,
                    expected_filename,
                    progress_data
                )

    await process.wait()

    return process.returncode


# ============================================================
# إرسال ملف صغير مباشرة بدون تقسيم
# ============================================================

async def send_small_file_directly(
    client,
    message,
    filepath,
    status_msg
):

    filename = os.path.basename(
        filepath
    )

    extension = os.path.splitext(
        filename
    )[1].lower()

    start_time = time.time()

    progress_args = (
        client,
        status_msg,
        start_time,
        filename
    )

    if extension in VIDEO_EXTENSIONS:

        await message.reply_video(
            video=filepath,
            progress=progress,
            progress_args=progress_args
        )

        return "video"

    if extension in IMAGE_EXTENSIONS:

        await message.reply_photo(
            photo=filepath,
            progress=progress,
            progress_args=progress_args
        )

        return "photo"

    if extension in AUDIO_EXTENSIONS:

        await message.reply_audio(
            audio=filepath,
            progress=progress,
            progress_args=progress_args
        )

        return "audio"

    await message.reply_document(
        document=filepath,
        progress=progress,
        progress_args=progress_args
    )

    return "document"


# ============================================================
# استخراج رابط التنزيل المباشر من MediaFire
# ============================================================

async def resolve_mediafire_url(
    mediafire_url
):

    timeout = ClientTimeout(
        total=30
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/115.0.0.0 "
            "Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,"
            "image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9"
    }

    async with ClientSession(
        timeout=timeout,
        headers=headers
    ) as session:

        async with session.get(
            mediafire_url,
            allow_redirects=True
        ) as response:

            if response.status != 200:

                raise RuntimeError(
                    f"MediaFire returned HTTP {response.status}"
                )

            html = await response.text(
                errors="ignore"
            )

            final_page_url = str(
                response.url
            )

    if not html:

        raise RuntimeError(
            "MediaFire returned an empty page."
        )

    html = unescape(
        html
    )

    # ========================================================
    # البحث عن زر التنزيل
    # ========================================================

    direct_url = None

    patterns = [

        r'<a[^>]+id=["\']downloadButton["\'][^>]+href=["\']([^"\']+)["\']',

        r'<a[^>]+href=["\']([^"\']+)["\'][^>]+id=["\']downloadButton["\']',

        r'<a[^>]+class=["\'][^"\']*download[^"\']*["\'][^>]+href=["\']([^"\']+)["\']',

        r'href=["\'](https?://download[^"\']+mediafire\.com/[^"\']+)["\']'
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            re.IGNORECASE
        )

        if match:

            direct_url = match.group(1)

            break

    if not direct_url:

        raise RuntimeError(
            "لم يتم العثور على رابط التنزيل المباشر في صفحة MediaFire."
        )

    direct_url = direct_url.strip()

    # ========================================================
    # معالجة الروابط النسبية
    # ========================================================

    if direct_url.startswith("//"):

        direct_url = "https:" + direct_url

    elif direct_url.startswith("/"):

        parsed_page = urlparse(
            final_page_url
        )

        direct_url = (
            f"{parsed_page.scheme}://"
            f"{parsed_page.netloc}"
            f"{direct_url}"
        )

    elif not direct_url.startswith(
        ("http://", "https://")
    ):

        direct_url = (
            final_page_url.rstrip("/")
            + "/"
            + direct_url.lstrip("/")
        )

    # ========================================================
    # استخراج اسم الملف من رابط التنزيل المباشر
    # ========================================================

    direct_filename = filename_from_url(
        direct_url
    )

    # ========================================================
    # محاولة الحصول على اسم الصفحة
    # ========================================================

    page_filename = None

    og_patterns = [

        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',

        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',

        r'<title[^>]*>(.*?)</title>'
    ]

    for pattern in og_patterns:

        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL
        )

        if match:

            candidate = unescape(
                match.group(1)
            ).strip()

            candidate = re.sub(
                r"\s+",
                " ",
                candidate
            )

            if candidate:

                page_filename = candidate

                break

    # ========================================================
    # اختيار الاسم النهائي
    # ========================================================

    if (
        direct_filename
        and direct_filename != "downloaded_file"
        and os.path.splitext(direct_filename)[1]
    ):

        final_filename = direct_filename

    elif page_filename:

        final_filename = page_filename

        # إزالة بعض العبارات المعتادة من عنوان MediaFire
        final_filename = re.sub(
            r"\s*[-|]\s*MediaFire.*$",
            "",
            final_filename,
            flags=re.IGNORECASE
        ).strip()

        # إذا كان الرابط المباشر يحتوي على امتداد،
        # نضيفه إلى اسم الصفحة.
        direct_extension = os.path.splitext(
            direct_filename
        )[1]

        if (
            direct_extension
            and not os.path.splitext(final_filename)[1]
        ):

            final_filename += direct_extension

    else:

        final_filename = direct_filename

    final_filename = safe_filename(
        final_filename
    )

    print(
        "🔥 MediaFire resolved successfully."
    )

    print(
        f"📄 MediaFire filename: {final_filename}"
    )

    print(
        f"🔗 MediaFire direct URL: {direct_url}"
    )

    return (
        direct_url,
        final_filename
    )


# ============================================================
# تنفيذ طلب MediaFire
# ============================================================

async def process_mediafire(
    client,
    message,
    mediafire_url
):

    try:

        # ====================================================
        # التحقق النهائي من الرابط
        # ====================================================

        if not is_mediafire_url(
            mediafire_url
        ):

            await message.reply_text(
                "❌ الرابط المرسل ليس رابط MediaFire صالحًا."
            )

            return

        # ====================================================
        # رسالة البداية
        # ====================================================

        status_msg = await message.reply_text(
            "🔥 **MediaFire**\n\n"
            "🔎 جاري استخراج رابط التنزيل المباشر..."
        )

        try:

            direct_url, filename = (
                await resolve_mediafire_url(
                    mediafire_url
                )
            )

        except Exception as resolve_error:

            print(
                f"❌ MediaFire extraction failed: "
                f"{resolve_error}"
            )

            try:
                await status_msg.delete()
            except Exception:
                pass

            await message.reply_text(
                "❌ **فشل استخراج رابط MediaFire.**\n\n"
                f"`{str(resolve_error)}`\n\n"
                "قد تكون صفحة MediaFire تغيّرت أو أن الرابط غير صالح."
            )

            return

        # ====================================================
        # إنشاء مجلد الطلب
        # ====================================================

        job_dir = None

        try:

            chat_id = message.chat.id

            job_dir = create_job_dir(
                chat_id
            )

            # =================================================
            # المرحلة 1/3
            # =================================================

            await status_msg.edit_text(
                "📥 **المرحلة [1/3]: تنزيل ملف MediaFire**\n\n"
                f"📄 **الملف:** `{filename}`\n\n"
                "⏳ جاري بدء التنزيل...",
                reply_markup=cancel_markup
            )

            quoted_url = shlex.quote(
                direct_url
            )

            quoted_job_dir = shlex.quote(
                job_dir
            )

            quoted_filename = shlex.quote(
                filename
            )

            cmd_aria = (
                f"aria2c "
                f"-x 4 "
                f"-s 4 "
                f"--min-split-size=10M "
                f"-k 1M "
                f"--max-tries=5 "
                f"--retry-wait=5 "
                f"--timeout=30 "
                f"--connect-timeout=10 "
                f"--max-file-not-found=5 "
                f"--summary-interval=5 "
                f"--content-disposition=true "
                f"--allow-overwrite=true "
                f"--file-allocation=none "
                f'--user-agent="Mozilla/5.0 '
                f'(Windows NT 10.0; Win64; x64) '
                f'AppleWebKit/537.36 '
                f'(KHTML, like Gecko) '
                f'Chrome/115.0.0.0 '
                f'Safari/537.36" '
                f"-d {quoted_job_dir} "
                f"-o {quoted_filename} "
                f"{quoted_url}"
            )

            print(
                "🔥 بدء تنزيل MediaFire باستخدام aria2..."
            )

            returncode = (
                await run_aria2_with_progress(
                    cmd_aria,
                    status_msg,
                    filename
                )
            )

            # =================================================
            # البحث عن الملف
            # =================================================

            downloaded_file = (
                find_downloaded_file(
                    job_dir
                )
            )

            if downloaded_file is None:

                try:
                    await status_msg.delete()
                except Exception:
                    pass

                await message.reply_text(
                    "❌ **فشل تنزيل ملف MediaFire.**\n\n"
                    "لم يتم العثور على الملف بعد انتهاء aria2."
                )

                return

            # =================================================
            # التحقق من الحجم
            # =================================================

            file_size = os.path.getsize(
                downloaded_file
            )

            if file_size <= 0:

                try:
                    await status_msg.delete()
                except Exception:
                    pass

                await message.reply_text(
                    "❌ **فشل تنزيل ملف MediaFire.**\n\n"
                    "تم إنشاء ملف فارغ."
                )

                return

            # =================================================
            # التحقق من aria2
            # =================================================

            if returncode != 0:

                try:
                    await status_msg.delete()
                except Exception:
                    pass

                await message.reply_text(
                    "❌ **فشل تنزيل ملف MediaFire.**\n\n"
                    "لم يكتمل التنزيل بنجاح."
                )

                return

            # =================================================
            # فرض الاسم النهائي
            # =================================================

            current_filename = os.path.basename(
                downloaded_file
            )

            if current_filename != filename:

                new_path = os.path.join(
                    job_dir,
                    filename
                )

                try:

                    os.rename(
                        downloaded_file,
                        new_path
                    )

                    downloaded_file = new_path

                except Exception as rename_error:

                    print(
                        f"⚠️ تعذر تغيير اسم الملف: "
                        f"{rename_error}"
                    )

            original_filename = os.path.basename(
                downloaded_file
            )

            size_mb = file_size / (
                1024 * 1024
            )

            print(
                f"✅ اكتمل تنزيل MediaFire: "
                f"{original_filename} "
                f"({size_mb:.1f} MB)"
            )

            # =================================================
            # أقل من الحد — إرسال مباشر
            # =================================================

            if file_size < DIRECT_UPLOAD_LIMIT:

                await status_msg.edit_text(
                    "📤 **جاري إرسال الملف مباشرة**\n\n"
                    f"📄 **الملف:** `{original_filename}`\n"
                    f"📊 **الحجم:** `{size_mb:.1f} MB`\n\n"
                    "✅ الحجم أقل من حد التقسيم، "
                    "لذلك لن يتم تقسيم الملف.",
                    reply_markup=cancel_markup
                )

                print(
                    f"📤 إرسال MediaFire مباشرة: "
                    f"{original_filename}"
                )

                try:

                    await send_small_file_directly(
                        client,
                        message,
                        downloaded_file,
                        status_msg
                    )

                except Exception as upload_error:

                    print(
                        f"❌ فشل إرسال MediaFire: "
                        f"{upload_error}"
                    )

                    try:
                        await status_msg.delete()
                    except Exception:
                        pass

                    await message.reply_text(
                        "❌ **فشل إرسال الملف.**\n\n"
                        "لم يتم اعتبار العملية ناجحة."
                    )

                    return

                try:
                    await status_msg.delete()
                except Exception:
                    pass

                await message.reply_text(
                    "🎉 **انتهت العملية بنجاح!**\n\n"
                    f"📄 **الملف:** `{original_filename}`\n"
                    f"📊 **الحجم:** `{size_mb:.1f} MB`\n"
                    "🔥 المصدر: MediaFire\n"
                    "✅ تم إرسال الملف مباشرة بدون تقسيم."
                )

                return

            # =================================================
            # الملف كبير — تقسيم
            # =================================================

            await asyncio.sleep(1)

            await status_msg.edit_text(
                "✂️ **المرحلة [2/3]: تقسيم الملف**\n\n"
                f"📄 **الملف:** `{original_filename}`\n"
                f"📊 **الحجم:** `{size_mb:.1f} MB`\n\n"
                "⚙️ جاري تقسيم الملف إلى أجزاء أقل من 1GB..."
            )

            archive_base = os.path.join(
                job_dir,
                os.path.splitext(
                    original_filename
                )[0] + ".7z"
            )

            cmd_7z = (
                f"cd {shlex.quote(job_dir)} && "
                f"7z a "
                f"-v1000m "
                f"-mx0 "
                f"{shlex.quote(archive_base)} "
                f"{shlex.quote(downloaded_file)}"
            )

            print(
                "✂️ بدء تقسيم ملف MediaFire..."
            )

            process7z = (
                await asyncio.create_subprocess_shell(
                    cmd_7z
                )
            )

            await process7z.wait()

            if process7z.returncode != 0:

                try:
                    await status_msg.delete()
                except Exception:
                    pass

                await message.reply_text(
                    "❌ **حدث خطأ أثناء تقسيم ملف MediaFire.**"
                )

                cleanup_processes()

                return

            print(
                "✅ اكتمل تقسيم ملف MediaFire."
            )

            # =================================================
            # حذف الملف الأصلي
            # =================================================

            if os.path.exists(
                downloaded_file
            ):

                os.remove(
                    downloaded_file
                )

            # =================================================
            # البحث عن الأجزاء
            # =================================================

            archive_prefix = (
                os.path.splitext(
                    original_filename
                )[0] + ".7z."
            )

            files = sorted(
                [
                    os.path.join(
                        job_dir,
                        f
                    )
                    for f in os.listdir(
                        job_dir
                    )
                    if f.startswith(
                        archive_prefix
                    )
                ]
            )

            if not files:

                await message.reply_text(
                    "❌ **لم يتم العثور على أجزاء ملف MediaFire.**"
                )

                return

            # =================================================
            # المرحلة 3/3
            # =================================================

            await status_msg.edit_text(
                "📤 **المرحلة [3/3]: رفع الأجزاء**\n\n"
                f"📄 **الملف الأصلي:** `{original_filename}`\n"
                f"📦 **عدد الأجزاء:** `{len(files)}`\n\n"
                "🚀 جاري رفع الأجزاء إلى Telegram..."
            )

            uploaded_count = 0

            for index, filepath in enumerate(
                files,
                start=1
            ):

                filename_part = os.path.basename(
                    filepath
                )

                part_status = (
                    await message.reply_text(
                        f"📤 **رفع الجزء {index}/{len(files)}**\n\n"
                        f"📦 `{filename_part}`\n\n"
                        "⏳ جاري الرفع...",
                        reply_markup=cancel_markup
                    )
                )

                start_time = time.time()

                try:

                    await message.reply_document(
                        document=filepath,
                        progress=progress,
                        progress_args=(
                            client,
                            part_status,
                            start_time,
                            filename_part
                        )
                    )

                except Exception as upload_error:

                    print(
                        f"❌ فشل رفع جزء MediaFire "
                        f"{index}: {upload_error}"
                    )

                    try:
                        await part_status.delete()
                    except Exception:
                        pass

                    await message.reply_text(
                        f"❌ **فشل رفع الجزء "
                        f"{index}/{len(files)}.**\n\n"
                        "لن يتم اعتبار العملية ناجحة."
                    )

                    return

                uploaded_count += 1

                print(
                    f"✅ تم رفع جزء MediaFire "
                    f"{uploaded_count}/{len(files)}"
                )

                try:
                    await part_status.delete()
                except Exception:
                    pass

                if os.path.exists(
                    filepath
                ):

                    os.remove(
                        filepath
                    )

            # =================================================
            # التأكد من جميع الأجزاء
            # =================================================

            if uploaded_count != len(files):

                await message.reply_text(
                    "❌ **لم يتم إرسال جميع أجزاء MediaFire.**\n\n"
                    "لن نعتبر العملية مكتملة."
                )

                return

            # =================================================
            # النجاح
            # =================================================

            await message.reply_text(
                "🎉 **تمت العملية بنجاح!**\n\n"
                f"📄 **الملف الأصلي:** `{original_filename}`\n"
                f"📦 **عدد الأجزاء:** `{uploaded_count}`\n\n"
                "🔥 المصدر: MediaFire\n"
                "✅ تم استخراج رابط التنزيل.\n"
                "✅ تم تنزيل الملف.\n"
                "✅ تم الحفاظ على الاسم الأصلي.\n"
                "✅ تم التقسيم بدون ضغط.\n"
                "✅ تم إرسال جميع الأجزاء.\n"
                "🗑️ تم تنظيف الملفات المؤقتة."
            )

        finally:

            if job_dir:

                cleanup_job_dir(
                    job_dir
                )

    except Exception as e:

        print(
            f"❌ خطأ في طلب MediaFire: {e}"
        )

        try:

            await message.reply_text(
                "❌ **حدث خطأ غير متوقع أثناء معالجة MediaFire.**\n\n"
                f"`{str(e)}`"
            )

        except Exception:
            pass


# ============================================================
# تنفيذ طلب عادي
# ============================================================

async def process_splitting(
    client,
    message,
    url
):

    job_dir = None

    try:

        chat_id = message.chat.id

        # ====================================================
        # إنشاء مجلد مستقل للطلب
        # ====================================================

        job_dir = create_job_dir(
            chat_id
        )

        expected_filename = safe_filename(
            filename_from_url(url)
        )

        # ====================================================
        # المرحلة 1/3 — التنزيل
        # ====================================================

        msg1 = await message.reply_text(
            "📥 **المرحلة [1/3]: تنزيل الملف**\n\n"
            f"📄 **الملف:** `{expected_filename}`\n\n"
            "⏳ جاري الاتصال بمصدر الملف...",
            reply_markup=cancel_markup
        )

        # ====================================================
        # إعدادات aria2
        # ====================================================

        quoted_url = shlex.quote(
            url
        )

        quoted_job_dir = shlex.quote(
            job_dir
        )

        cmd_aria = (
            f"aria2c "
            f"-x 4 "
            f"-s 4 "
            f"--min-split-size=10M "
            f"-k 1M "
            f"--max-tries=5 "
            f"--retry-wait=5 "
            f"--timeout=30 "
            f"--connect-timeout=10 "
            f"--max-file-not-found=5 "
            f"--summary-interval=5 "
            f"--content-disposition=true "
            f"--allow-overwrite=true "
            f"--file-allocation=none "
            f'--user-agent="Mozilla/5.0 '
            f'(Windows NT 10.0; Win64; x64) '
            f'AppleWebKit/537.36 '
            f'(KHTML, like Gecko) '
            f'Chrome/115.0.0.0 '
            f'Safari/537.36" '
            f"-d {quoted_job_dir} "
            f"{quoted_url}"
        )

        print(
            "⬇️ بدء التنزيل باستخدام aria2..."
        )

        returncode = (
            await run_aria2_with_progress(
                cmd_aria,
                msg1,
                expected_filename
            )
        )

        # ====================================================
        # البحث عن الملف
        # ====================================================

        downloaded_file = (
            find_downloaded_file(
                job_dir
            )
        )

        if downloaded_file is None:

            try:
                await msg1.delete()
            except Exception:
                pass

            await message.reply_text(
                "❌ **فشل التنزيل!**\n\n"
                "لم يتم العثور على الملف بعد انتهاء aria2."
            )

            return

        # ====================================================
        # التحقق من حجم الملف
        # ====================================================

        file_size = os.path.getsize(
            downloaded_file
        )

        if file_size <= 0:

            try:
                await msg1.delete()
            except Exception:
                pass

            await message.reply_text(
                "❌ **فشل التنزيل!**\n\n"
                "تم إنشاء ملف فارغ."
            )

            return

        # ====================================================
        # التحقق من نتيجة aria2
        # ====================================================

        if returncode != 0:

            try:
                await msg1.delete()
            except Exception:
                pass

            await message.reply_text(
                "❌ **فشل التنزيل!**\n\n"
                "لم يكتمل التنزيل بنجاح."
            )

            return

        # ====================================================
        # الحصول على الاسم الأصلي
        # ====================================================

        original_filename = os.path.basename(
            downloaded_file
        )

        if (
            original_filename
            in [
                "download",
                "downloaded_file"
            ]
            and expected_filename
        ):

            new_path = os.path.join(
                job_dir,
                expected_filename
            )

            try:

                os.rename(
                    downloaded_file,
                    new_path
                )

                downloaded_file = new_path

                original_filename = (
                    expected_filename
                )

            except Exception:
                pass

        # ====================================================
        # نجاح التنزيل
        # ====================================================

        size_mb = file_size / (
            1024 * 1024
        )

        print(
            f"✅ اكتمل التنزيل: "
            f"{original_filename} "
            f"({size_mb:.1f} MB)"
        )

        print(
            f"📦 حجم الملف النهائي: "
            f"{size_mb:.1f} MB"
        )

        # ====================================================
        # الملف تحت حد التقسيم — إرسال مباشر
        # ====================================================

        if file_size < DIRECT_UPLOAD_LIMIT:

            await msg1.edit_text(
                "📤 **جاري إرسال الملف مباشرة**\n\n"
                f"📄 **الملف:** `{original_filename}`\n"
                f"📊 **الحجم:** `{size_mb:.1f} MB`\n\n"
                "✅ الحجم أقل من حد التقسيم، "
                "لذلك لن يتم تقسيم الملف.",
                reply_markup=cancel_markup
            )

            print(
                f"📤 إرسال مباشر: "
                f"{original_filename}"
            )

            try:

                await send_small_file_directly(
                    client,
                    message,
                    downloaded_file,
                    msg1
                )

            except Exception as upload_error:

                print(
                    f"❌ فشل الإرسال المباشر: "
                    f"{upload_error}"
                )

                try:
                    await msg1.delete()
                except Exception:
                    pass

                await message.reply_text(
                    "❌ **فشل إرسال الملف.**\n\n"
                    "لم يتم اعتبار العملية ناجحة."
                )

                return

            try:
                await msg1.delete()
            except Exception:
                pass

            print(
                f"✅ تم إرسال الملف مباشرة: "
                f"{original_filename}"
            )

            await message.reply_text(
                "🎉 **انتهت العملية بنجاح!**\n\n"
                f"📄 **الملف:** `{original_filename}`\n"
                f"📊 **الحجم:** `{size_mb:.1f} MB`\n"
                "✅ تم إرسال الملف مباشرة بدون تقسيم."
            )

            return

        # ====================================================
        # الملف يساوي أو يتجاوز الحد — التقسيم الحالي
        # ====================================================

        await asyncio.sleep(1)

        await msg1.edit_text(
            "✂️ **المرحلة [2/3]: تقسيم الملف**\n\n"
            f"📄 **الملف:** `{original_filename}`\n"
            f"📊 **الحجم:** `{size_mb:.1f} MB`\n\n"
            "⚙️ جاري تقسيم الملف إلى أجزاء أقل من 1GB..."
        )

        archive_base = os.path.join(
            job_dir,
            os.path.splitext(
                original_filename
            )[0] + ".7z"
        )

        cmd_7z = (
            f"cd {shlex.quote(job_dir)} && "
            f"7z a "
            f"-v1000m "
            f"-mx0 "
            f"{shlex.quote(archive_base)} "
            f"{shlex.quote(downloaded_file)}"
        )

        print(
            "✂️ بدء تقسيم الملف..."
        )

        process7z = (
            await asyncio.create_subprocess_shell(
                cmd_7z
            )
        )

        await process7z.wait()

        if process7z.returncode != 0:

            try:
                await msg1.delete()
            except Exception:
                pass

            await message.reply_text(
                "❌ **حدث خطأ أثناء تقسيم الملف.**"
            )

            cleanup_processes()

            return

        print(
            "✅ اكتمل تقسيم الملف."
        )

        # ====================================================
        # حذف الملف الأصلي بعد نجاح التقسيم
        # ====================================================

        if os.path.exists(
            downloaded_file
        ):

            os.remove(
                downloaded_file
            )

        # ====================================================
        # البحث عن الأجزاء
        # ====================================================

        archive_prefix = (
            os.path.splitext(
                original_filename
            )[0] + ".7z."
        )

        files = sorted(
            [
                os.path.join(
                    job_dir,
                    f
                )
                for f in os.listdir(
                    job_dir
                )
                if f.startswith(
                    archive_prefix
                )
            ]
        )

        if not files:

            await message.reply_text(
                "❌ **لم يتم العثور على أجزاء الملف.**"
            )

            return

        # ====================================================
        # المرحلة 3/3 — الرفع
        # ====================================================

        await msg1.edit_text(
            "📤 **المرحلة [3/3]: رفع الأجزاء**\n\n"
            f"📄 **الملف الأصلي:** `{original_filename}`\n"
            f"📦 **عدد الأجزاء:** `{len(files)}`\n\n"
            "🚀 جاري رفع الأجزاء إلى Telegram..."
        )

        # ====================================================
        # رفع الأجزاء
        # ====================================================

        uploaded_count = 0

        for index, filepath in enumerate(
            files,
            start=1
        ):

            filename = os.path.basename(
                filepath
            )

            status_msg = (
                await message.reply_text(
                    f"📤 **رفع الجزء {index}/{len(files)}**\n\n"
                    f"📦 `{filename}`\n\n"
                    "⏳ جاري الرفع...",
                    reply_markup=cancel_markup
                )
            )

            start_time = time.time()

            try:

                await message.reply_document(
                    document=filepath,
                    progress=progress,
                    progress_args=(
                        client,
                        status_msg,
                        start_time,
                        filename
                    )
                )

            except Exception as upload_error:

                print(
                    f"❌ فشل رفع الجزء {index}: "
                    f"{upload_error}"
                )

                try:
                    await status_msg.delete()
                except Exception:
                    pass

                await message.reply_text(
                    f"❌ **فشل رفع الجزء "
                    f"{index}/{len(files)}.**\n\n"
                    "لن يتم اعتبار العملية ناجحة."
                )

                return

            # =================================================
            # نجاح الرفع
            # =================================================

            uploaded_count += 1

            print(
                f"✅ تم رفع الجزء "
                f"{uploaded_count}/{len(files)}"
            )

            try:
                await status_msg.delete()
            except Exception:
                pass

            # =================================================
            # حذف الجزء بعد نجاح إرساله
            # =================================================

            if os.path.exists(
                filepath
            ):

                os.remove(
                    filepath
                )

        # ====================================================
        # التأكد أن كل الأجزاء أُرسلت
        # ====================================================

        if uploaded_count != len(files):

            await message.reply_text(
                "❌ **لم يتم إرسال جميع الأجزاء.**\n\n"
                "لن نعتبر العملية مكتملة."
            )

            return

        # ====================================================
        # نجاح كامل
        # ====================================================

        await message.reply_text(
            "🎉 **تمت العملية بنجاح!**\n\n"
            f"📄 **الملف الأصلي:** `{original_filename}`\n"
            f"📦 **عدد الأجزاء:** `{uploaded_count}`\n\n"
            "✅ تم التنزيل.\n"
            "✅ تم الحفاظ على الاسم الأصلي.\n"
            "✅ تم التقسيم بدون ضغط.\n"
            "✅ تم إرسال جميع الأجزاء.\n"
            "🗑️ تم تنظيف الملفات المؤقتة."
        )

    except Exception as e:

        print(
            f"❌ خطأ في الطلب: {e}"
        )

        try:

            await message.reply_text(
                "❌ **حدث خطأ غير متوقع أثناء العملية.**\n\n"
                f"`{str(e)}`"
            )

        except Exception:
            pass

    finally:

        if job_dir:

            cleanup_job_dir(
                job_dir
            )


# ============================================================
# عامل الطابور
# ============================================================

async def queue_worker():

    global active_user

    print(
        "📋 Queue worker started."
    )

    while True:

        while not job_queue:

            await asyncio.sleep(
                0.5
            )

        chat_id, message, url, mode = (
            job_queue.popleft()
        )

        active_user = chat_id

        print(
            f"▶️ بدأ طلب المستخدم: "
            f"{chat_id}"
        )

        print(
            f"📌 نوع الطلب: {mode}"
        )

        try:

            if mode == "mediafire":

                await process_mediafire(
                    app,
                    message,
                    url
                )

            else:

                await process_splitting(
                    app,
                    message,
                    url
                )

        except Exception as e:

            print(
                f"❌ خطأ في طلب المستخدم "
                f"{chat_id}: {e}"
            )

            try:

                await message.reply_text(
                    "❌ حدث خطأ أثناء معالجة طلبك."
                )

            except Exception:
                pass

        finally:

            print(
                f"✅ انتهى طلب المستخدم: "
                f"{chat_id}"
            )

            active_user = None


# ============================================================
# إضافة طلب إلى الطابور
# ============================================================

async def add_to_queue(
    message,
    url,
    mode="normal"
):

    chat_id = message.chat.id

    # ========================================================
    # المستخدم لديه عملية قيد التنفيذ
    # ========================================================

    if active_user == chat_id:

        await message.reply_text(
            "⚠️ **لديك عملية قيد التنفيذ بالفعل.**\n\n"
            "انتظر حتى تنتهي العملية الحالية."
        )

        return

    # ========================================================
    # منع تكرار طلب المستخدم في الطابور
    # ========================================================

    for queued_chat_id, _, _, _ in job_queue:

        if queued_chat_id == chat_id:

            await message.reply_text(
                "⚠️ **لديك طلب موجود بالفعل "
                "في قائمة الانتظار.**"
            )

            return

    # ========================================================
    # إضافة الطلب
    # ========================================================

    job_queue.append(
        (
            chat_id,
            message,
            url,
            mode
        )
    )

    position = len(
        job_queue
    )

    if (
        active_user is None
        and position == 1
    ):

        await message.reply_text(
            "🚀 **تم استلام طلبك!**\n\n"
            "سيبدأ التنفيذ الآن."
        )

    else:

        await message.reply_text(
            "⏳ **تمت إضافة طلبك إلى قائمة الانتظار.**\n\n"
            f"📍 **ترتيبك الحالي:** `{position}`\n"
            f"👥 **عدد الطلبات أمامك:** "
            f"`{position - 1}`"
        )


# ============================================================
# /split
# ============================================================

@app.on_message(
    filters.command("split")
    & filters.private
)
async def split_cmd(
    client,
    message
):

    args = message.text.split(
        maxsplit=1
    )

    if len(args) > 1:

        url = args[1].strip()

        if not url.startswith(
            ("http://", "https://")
        ):

            await message.reply_text(
                "❌ الرجاء إرسال رابط يبدأ بـ "
                "`http://` أو `https://`."
            )

            return

        if is_mediafire_url(
            url
        ):

            await message.reply_text(
                "🔥 هذا رابط MediaFire.\n\n"
                "استخدم الأمر `/mf` لمعالجته."
            )

            return

        await add_to_queue(
            message,
            url,
            "normal"
        )

    else:

        pending_links[
            message.chat.id
        ] = "split"

        await message.reply_text(
            "🔗 **أرسل رابط الملف الآن.**\n\n"
            "إذا كان السيرفر مشغولًا، "
            "سيتم وضع طلبك في قائمة الانتظار."
        )


# ============================================================
# /mf
# ============================================================

@app.on_message(
    filters.command("mf")
    & filters.private
)
async def mediafire_cmd(
    client,
    message
):

    args = message.text.split(
        maxsplit=1
    )

    # ========================================================
    # الرابط موجود مع الأمر
    # ========================================================

    if len(args) > 1:

        url = args[1].strip()

        if not url.startswith(
            ("http://", "https://")
        ):

            await message.reply_text(
                "❌ الرجاء إرسال رابط MediaFire صالح."
            )

            return

        if not is_mediafire_url(
            url
        ):

            await message.reply_text(
                "❌ هذا ليس رابط MediaFire.\n\n"
                "استخدم `/mf` فقط مع روابط MediaFire."
            )

            return

        await add_to_queue(
            message,
            url,
            "mediafire"
        )

        return

    # ========================================================
    # /mf بدون رابط
    # ========================================================

    pending_links[
        message.chat.id
    ] = "mediafire"

    await message.reply_text(
        "🔥 **MediaFire**\n\n"
        "أرسل رابط MediaFire الآن."
    )


# ============================================================
# استقبال الرابط
# ============================================================

@app.on_message(
    filters.text
    & ~filters.command(
        ["start", "split", "help", "mf"]
    )
)
async def text_handler(
    client,
    message
):

    chat_id = message.chat.id

    text = (
        message.text or ""
    ).strip()

    if not text:
        return

    # ========================================================
    # إذا كان المستخدم ينتظر رابطًا بعد أمر
    # ========================================================

    pending_mode = pending_links.get(
        chat_id
    )

    if pending_mode:

        pending_links[
            chat_id
        ] = False

        # ----------------------------------------------------
        # يجب أن يكون الرابط HTTP/HTTPS
        # ----------------------------------------------------

        if not text.startswith(
            ("http://", "https://")
        ):

            await message.reply_text(
                "❌ الرابط غير صالح.\n\n"
                "يجب أن يبدأ بـ "
                "`http://` أو `https://`."
            )

            return

        # ----------------------------------------------------
        # /mf
        # ----------------------------------------------------

        if pending_mode == "mediafire":

            if not is_mediafire_url(
                text
            ):

                await message.reply_text(
                    "❌ هذا ليس رابط MediaFire.\n\n"
                    "أرسل رابط MediaFire صالحًا."
                )

                return

            await add_to_queue(
                message,
                text,
                "mediafire"
            )

            return

        # ----------------------------------------------------
        # /split
        # ----------------------------------------------------

        if pending_mode == "split":

            if is_mediafire_url(
                text
            ):

                await message.reply_text(
                    "🔥 هذا رابط MediaFire.\n\n"
                    "استخدم `/mf` لمعالجته."
                )

                return

            await add_to_queue(
                message,
                text,
                "normal"
            )

            return

    # ========================================================
    # روابط MediaFire لا تعمل تلقائيًا
    # ========================================================

    if is_mediafire_url(
        text
    ):

        return

    # ========================================================
    # أي رابط HTTP/HTTPS عادي يبدأ تلقائيًا
    # ========================================================

    if text.startswith(
        ("http://", "https://")
    ):

        await add_to_queue(
            message,
            text,
            "normal"
        )

        return


# ============================================================
# إلغاء العملية
# ============================================================

@app.on_callback_query(
    filters.regex("cancel_process")
)
async def cancel_callback(
    client,
    callback_query
):

    global active_user

    chat_id = (
        callback_query.message.chat.id
    )

    if chat_id == active_user:

        cleanup_processes()

        pending_links[
            chat_id
        ] = False

        await callback_query.message.edit_text(
            "🚫 **تم طلب إلغاء العملية.**\n\n"
            "جاري تنظيف الملفات المؤقتة..."
        )

    else:

        await callback_query.answer(
            "هذه العملية ليست قيد التنفيذ حاليًا.",
            show_alert=True
        )


# ============================================================
# /start
# ============================================================

@app.on_message(
    filters.command("start")
    & filters.private
)
async def start_cmd(
    client,
    message
):

    await message.reply_text(
        "✨ **أهلاً بك في بوت التجزئة والرفع!** 🤖\n\n"
        "📌 **روابط عادية:**\n"
        "أرسل رابط HTTP/HTTPS مباشرة وسيبدأ التنزيل تلقائيًا.\n\n"
        "🔥 **MediaFire:**\n"
        "استخدم `/mf` ثم أرسل رابط MediaFire.\n\n"
        "📦 **الطريقة القديمة:**\n"
        "استخدم `/split` ثم أرسل الرابط."
    )


# ============================================================
# /help
# ============================================================

@app.on_message(
    filters.command("help")
    & filters.private
)
async def help_cmd(
    client,
    message
):

    await message.reply_text(
        "📖 **دليل الاستخدام:**\n\n"

        "🔗 **رابط عادي:**\n"
        "أرسل رابط `http://` أو `https://` مباشرة.\n\n"

        "🔥 **MediaFire:**\n"
        "استخدم `/mf` ثم أرسل رابط MediaFire.\n\n"

        "📦 **/split:**\n"
        "ما زال يعمل بالطريقة القديمة.\n\n"

        "📌 **طريقة المعالجة:**\n"
        "1️⃣ يتم تنزيل الملف باسمه الأصلي.\n"
        "2️⃣ إذا كان أقل من 1000 MiB يُرسل مباشرة.\n"
        "3️⃣ إذا بلغ 1000 MiB أو أكثر يتم تقسيمه.\n"
        "4️⃣ التقسيم بدون ضغط.\n"
        "5️⃣ يتم إرسال جميع الأجزاء إلى Telegram.\n"
        "6️⃣ يتم تنظيف الملفات المؤقتة بعد الانتهاء."
    )


# ============================================================
# Web Server
# ============================================================

async def handle(request):

    return web.Response(
        text="Bot is alive!"
    )


async def start_web_server():

    server = web.Application()

    server.router.add_get(
        "/",
        handle
    )

    runner = web.AppRunner(
        server
    )

    await runner.setup()

    await web.TCPSite(
        runner,
        "0.0.0.0",
        int(
            os.environ.get(
                "PORT",
                8080
            )
        )
    ).start()


# ============================================================
# Main
# ============================================================

async def main():

    global queue_worker_task

    await start_web_server()

    await app.start()

    print(
        "================================"
    )

    print(
        "Telegram connection: OK"
    )

    me = await app.get_me()

    print(
        f"Bot username: @{me.username}"
    )

    print(
        f"Bot ID: {me.id}"
    )

    print(
        "================================"
    )

    queue_worker_task = asyncio.create_task(
        queue_worker()
    )

    print(
        "🚀 Telegram Splitter يعمل الآن."
    )

    await asyncio.Event().wait()


# ============================================================
# التشغيل
# ============================================================

if __name__ == "__main__":

    loop = asyncio.get_event_loop()

    loop.run_until_complete(
        main()
    )
