import os
import re
import asyncio
import time
import sqlite3

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from yt_dlp import YoutubeDL


# ==================================================
# KONFIGURASI
# ==================================================

TOKEN = "ISI_TOKEN_BOT_KAMU"

# Masukkan Telegram ID kamu nanti
ADMIN_ID = 123456789

DOWNLOAD_DIR = "downloads"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ==================================================
# DATABASE
# ==================================================

DB_FILE = "users.db"


def init_database():

    conn = sqlite3.connect(DB_FILE)

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            downloads INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


def register_user(user):

    conn = sqlite3.connect(DB_FILE)

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            downloads
        )
        VALUES (?, ?, ?, 0)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """, (
        user.id,
        user.username,
        user.first_name
    ))

    conn.commit()
    conn.close()


def add_download(user_id):

    conn = sqlite3.connect(DB_FILE)

    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET downloads = downloads + 1
        WHERE user_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()


def get_statistics():

    conn = sqlite3.connect(DB_FILE)

    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM users"
    )

    total_users = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COALESCE(SUM(downloads), 0) FROM users"
    )

    total_downloads = cursor.fetchone()[0]

    conn.close()

    return total_users, total_downloads


# ==================================================
# FORMAT UKURAN
# ==================================================

def format_size(size):

    if not size:
        return "0 B"

    units = [
        "B",
        "KB",
        "MB",
        "GB"
    ]

    index = 0

    while (
        size >= 1024
        and index < len(units) - 1
    ):

        size /= 1024
        index += 1

    return f"{size:.1f} {units[index]}"


# ==================================================
# FORMAT WAKTU
# ==================================================

def format_time(seconds):

    if seconds is None:
        return "?"

    seconds = int(seconds)

    minutes = seconds // 60

    seconds = seconds % 60

    if minutes > 0:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


# ==================================================
# PROGRESS BAR
# ==================================================

def make_progress(percent):

    total = 20

    filled = int(
        total * percent / 100
    )

    empty = total - filled

    return (
        "█" * filled
        + "░" * empty
    )


# ==================================================
# MENU UTAMA
# ==================================================

def main_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "📥 Download Video",
                callback_data="download"
            )
        ],

        [
            InlineKeyboardButton(
                "🎵 Video → MP3",
                callback_data="mp3"
            )
        ],

        [
            InlineKeyboardButton(
                "ℹ️ Bantuan",
                callback_data="help"
            )
        ]

    ]

    return InlineKeyboardMarkup(keyboard)


# ==================================================
# /START
# ==================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user:
        register_user(
            update.effective_user
        )

    text = (
        "🤖 *CHALLS DOWNLOADER*\n\n"

        "Download video dari berbagai situs "
        "yang didukung oleh yt-dlp.\n\n"

        "📥 *Download Video*\n"
        "Kirim link video dan bot akan "
        "mencoba mendownloadnya.\n\n"

        "🎵 *Video → MP3*\n"
        "Kirim link kemudian gunakan menu MP3.\n\n"

        "⚡ Cepat • Simple • Otomatis\n\n"

        "👇 Pilih menu:"
    )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# ==================================================
# TOMBOL MENU
# ==================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if query.data == "download":

        await query.message.reply_text(
            "📥 *Download Video*\n\n"
            "Kirim link video yang ingin "
            "kamu download.",
            parse_mode="Markdown"
        )

    elif query.data == "mp3":

        context.user_data["mode"] = "mp3"

        await query.message.reply_text(
            "🎵 *Video → MP3*\n\n"
            "Kirim link video.\n\n"
            "Bot akan mencoba mengambil audio "
            "dan mengubahnya menjadi MP3.",
            parse_mode="Markdown"
        )

    elif query.data == "help":

        await query.message.reply_text(
            "ℹ️ *BANTUAN CHALLS DOWNLOADER*\n\n"

            "1️⃣ Tekan Download Video\n"
            "2️⃣ Kirim link video\n"
            "3️⃣ Tunggu proses download\n"
            "4️⃣ Bot mengirim file secara otomatis\n\n"

            "🎵 Untuk MP3, pilih menu "
            "Video → MP3 lalu kirim link.\n\n"

            "⚠️ Gunakan link yang bisa diakses "
            "secara publik.",
            parse_mode="Markdown"
        )


# ==================================================
# VALIDASI URL
# ==================================================

def valid_url(url):

    return re.match(
        r"^https?://",
        url
    )


# ==================================================
# DOWNLOAD VIDEO
# ==================================================

async def download_video(
    update,
    url,
    status
):

    loop = asyncio.get_running_loop()

    last_update = [0]

    output = os.path.join(
        DOWNLOAD_DIR,
        "%(title)s.%(ext)s"
    )

    async def show_progress(data):

        if data.get("status") != "downloading":
            return

        downloaded = data.get(
            "downloaded_bytes",
            0
        )

        total = (
            data.get("total_bytes")
            or data.get("total_bytes_estimate")
            or 0
        )

        if not total:
            return

        percent = (
            downloaded / total * 100
        )

        speed = data.get("speed") or 0

        eta = data.get("eta")

        now = time.time()

        if now - last_update[0] < 2:
            return

        last_update[0] = now

        bar = make_progress(percent)

        text = (
            "⬇️ *DOWNLOAD*\n\n"
            f"`{bar}`\n\n"
            f"📊 {percent:.1f}%\n"
            f"📦 {format_size(downloaded)} / "
            f"{format_size(total)}\n"
            f"⚡ {format_size(speed)}/s\n"
            f"⏱️ ETA: {format_time(eta)}"
        )

        try:

            await status.edit_text(
                text,
                parse_mode="Markdown"
            )

        except Exception:
            pass

    def progress_hook(data):

        if data.get("status") == "downloading":

            asyncio.run_coroutine_threadsafe(
                show_progress(data),
                loop
            )

    options = {

        "outtmpl": output,

        "format":
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "best[ext=mp4]/best",

        "merge_output_format": "mp4",

        "noplaylist": True,

        "quiet": True,

        "no_warnings": True,

        "restrictfilenames": True,

        "progress_hooks": [
            progress_hook
        ]
    }

    def do_download():

        with YoutubeDL(options) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

            filename = ydl.prepare_filename(
                info
            )

            if (
                not os.path.exists(filename)
                and filename.endswith(".webm")
            ):

                filename = filename[:-5] + ".mp4"

            elif (
                not os.path.exists(filename)
                and filename.endswith(".mkv")
            ):

                filename = filename[:-4] + ".mp4"

            return filename

    filename = await asyncio.to_thread(
        do_download
    )

    if (
        not filename
        or not os.path.exists(filename)
    ):

        raise Exception(
            "File hasil download tidak ditemukan."
        )

    return filename


# ==================================================
# DOWNLOAD MP3
# ==================================================

async def download_mp3(
    update,
    url,
    status
):

    output = os.path.join(
        DOWNLOAD_DIR,
        "%(title)s.%(ext)s"
    )

    options = {

        "outtmpl": output,

        "format": "bestaudio/best",

        "noplaylist": True,

        "quiet": True,

        "no_warnings": True,

        "restrictfilenames": True,

        "postprocessors": [

            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192"
            }

        ]
    }

    def do_download():

        with YoutubeDL(options) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

            original = ydl.prepare_filename(
                info
            )

            base = os.path.splitext(
                original
            )[0]

            return base + ".mp3"

    filename = await asyncio.to_thread(
        do_download
    )

    if (
        not filename
        or not os.path.exists(filename)
    ):

        raise Exception(
            "File MP3 tidak ditemukan."
        )

    return filename


# ==================================================
# TERIMA LINK
# ==================================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_user:
        return

    register_user(
        update.effective_user
    )

    url = update.message.text.strip()

    if not valid_url(url):

        await update.message.reply_text(
            "❌ Link tidak valid.\n\n"
            "Pastikan link diawali "
            "http:// atau https://"
        )

        return

    status = await update.message.reply_text(
        "🔎 Memeriksa link..."
    )

    filename = None

    mode = context.user_data.get(
        "mode",
        "video"
    )

    context.user_data["mode"] = "video"

    try:

        if mode == "mp3":

            await status.edit_text(
                "🎵 Mengambil audio..."
            )

            filename = await download_mp3(
                update,
                url,
                status
            )

            caption = (
                "🎵 *CHALLS MP3*\n\n"
                "✅ Download berhasil!"
            )

        else:

            await status.edit_text(
                "🔎 Mengambil informasi video..."
            )

            filename = await download_video(
                update,
                url,
                status
            )

            caption = (
                "✅ *CHALLS DOWNLOADER*\n\n"
                "Download berhasil!"
            )

        await status.edit_text(
            "✅ Download selesai!\n\n"
            "📤 Mengirim file..."
        )

        file_size = os.path.getsize(
            filename
        )

        if file_size > 50 * 1024 * 1024:

            await status.edit_text(
                "❌ File terlalu besar.\n\n"
                f"Ukuran: {format_size(file_size)}"
            )

            return

        with open(
            filename,
            "rb"
        ) as file:

            await update.message.reply_document(
                document=file,
                caption=caption,
                parse_mode="Markdown"
            )

        add_download(
            update.effective_user.id
        )

        try:
            await status.delete()
        except Exception:
            pass

    except Exception as error:

        print(
            "ERROR:",
            repr(error)
        )

        try:

            await status.edit_text(
                "❌ *Download gagal.*\n\n"
                "Pastikan link dapat diakses dan "
                "didukung oleh yt-dlp.",
                parse_mode="Markdown"
            )

        except Exception:
            pass

    finally:

        if filename and os.path.exists(filename):

            try:
                os.remove(filename)

                print(
                    "🗑️ File dihapus:",
                    filename
                )

            except Exception as error:

                print(
                    "❌ Gagal menghapus:",
                    error
                )


# ==================================================
# /STATS
# ==================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Perintah ini khusus admin."
        )

        return

    total_users, total_downloads = (
        get_statistics()
    )

    await update.message.reply_text(

        "📊 *STATISTIK CHALLS BOT*\n\n"

        f"👤 Total pengguna: `{total_users}`\n"
        f"📥 Total download: `{total_downloads}`",

        parse_mode="Markdown"
    )


# ==================================================
# /ID
# ==================================================

async def get_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        f"🆔 Telegram ID kamu:\n\n"
        f"`{update.effective_user.id}`",

        parse_mode="Markdown"
    )


# ==================================================
# /ADMIN
# ==================================================

async def admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Akses ditolak."
        )

        return

    total_users, total_downloads = (
        get_statistics()
    )

    await update.message.reply_text(

        "👑 *ADMIN PANEL*\n\n"

        f"👤 Users: `{total_users}`\n"
        f"📥 Downloads: `{total_downloads}`\n\n"

        "Perintah:\n"
        "/stats - Statistik bot\n"
        "/id - Melihat Telegram ID",

        parse_mode="Markdown"
    )


# ==================================================
# ERROR HANDLER
# ==================================================

async def error_handler(
    update,
    context
):

    print(
        "ERROR:",
        repr(context.error)
    )


# ==================================================
# MAIN
# ==================================================

def main():

    init_database()

    if TOKEN == "ISI_TOKEN_BOT_KAMU":

        print(
            "❌ TOKEN BELUM DIISI!"
        )

        return

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin
        )
    )

    app.add_handler(
        CommandHandler(
            "id",
            get_id
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_link
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        "🤖 CHALLS Downloader sedang berjalan..."
    )

    app.run_polling()


# ==================================================
# JALANKAN BOT
# ==================================================

if __name__ == "__main__":
    main()
