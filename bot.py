import asyncio
import logging
import os
import shutil
import sqlite3
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputSticker, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = Path("stickerbot.db")
WORK_DIR = Path("/tmp/stickerbot_work")
LIMIT_PER_PACK = 120
DEFAULT_EMOJI = "🙂"
COMMON_EMOJIS = ["🔥", "😂", "❤️", "😍", "😎", "👍", "💯", "🤯"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sticker-bot")

DB_LOCK = threading.Lock()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
WORK_DIR.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row


def init_db() -> None:
    with DB_LOCK:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                default_emoji TEXT NOT NULL DEFAULT '🙂',
                next_static_index INTEGER NOT NULL DEFAULT 1,
                next_video_index INTEGER NOT NULL DEFAULT 1,
                total_stickers INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS packs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('static', 'video')),
                pack_index INTEGER NOT NULL,
                short_name TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                sticker_count INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS stickers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                pack_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                emoji TEXT NOT NULL,
                keywords TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()


def db_one(query: str, params: Tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
    with DB_LOCK:
        cur = conn.execute(query, params)
        row = cur.fetchone()
        cur.close()
        return row


def db_all(query: str, params: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
    with DB_LOCK:
        cur = conn.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        return rows


def db_execute(query: str, params: Tuple[Any, ...] = ()) -> None:
    with DB_LOCK:
        conn.execute(query, params)
        conn.commit()


def ensure_user(user_id: int) -> None:
    with DB_LOCK:
        conn.execute(
            "INSERT OR IGNORE INTO users(user_id) VALUES(?)",
            (user_id,),
        )
        conn.commit()


def get_user(user_id: int) -> sqlite3.Row:
    ensure_user(user_id)
    row = db_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    assert row is not None
    return row


def set_user_default_emoji(user_id: int, emoji: str) -> None:
    ensure_user(user_id)
    db_execute("UPDATE users SET default_emoji = ? WHERE user_id = ?", (emoji, user_id))


def inc_user_total_stickers(user_id: int, delta: int = 1) -> None:
    db_execute("UPDATE users SET total_stickers = MAX(total_stickers + ?, 0) WHERE user_id = ?", (delta, user_id))


async def warm_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    cached = context.application.bot_data.get("bot_username")
    if cached:
        return cached
    me = await context.bot.get_me()
    if not me.username:
        raise RuntimeError("Bot username missing")
    context.application.bot_data["bot_username"] = me.username.lower()
    return context.application.bot_data["bot_username"]


def build_short_name(user_id: int, kind: str, index: int, bot_username: str) -> str:
    suffix = f"_by_{bot_username.lower()}"
    core = f"stk_{user_id}_{kind}_{index}"
    core = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in core)
    core = "_".join(filter(None, core.split("_")))
    core = core.strip("_")
    if not core or not core[0].isalpha():
        core = f"stk_{core}" if core else "stk"
    name = f"{core}{suffix}"
    name = name[:64]
    if not name.endswith(suffix):
        prefix_len = 64 - len(suffix)
        prefix = name[:prefix_len].rstrip("_")
        name = f"{prefix}{suffix}"
    return name[:64]


def truncate_title(title: str) -> str:
    return title[:64]


def kind_label(kind: str) -> str:
    return "الصورة" if kind == "static" else "الفيديو"


def kind_from_message(message) -> Optional[str]:
    if message.photo:
        return "static"
    if message.video or message.animation:
        return "video"
    if message.document:
        mime = (message.document.mime_type or "").lower()
        name = (message.document.file_name or "").lower()
        ext = Path(name).suffix
        if mime.startswith("image/") or ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif"}:
            return "static"
        if mime.startswith("video/") or mime == "image/gif" or ext in {".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".mpeg", ".mpg", ".m4v", ".gif"}:
            return "video"
    return None


def make_workdir(user_id: int) -> Path:
    path = WORK_DIR / str(user_id) / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


async def download_media(message, destination: Path) -> None:
    tg_file = None
    if message.photo:
        tg_file = await message.photo[-1].get_file()
    elif message.video:
        tg_file = await message.video.get_file()
    elif message.animation:
        tg_file = await message.animation.get_file()
    elif message.document:
        tg_file = await message.document.get_file()
    else:
        raise ValueError("Unsupported message type")
    await tg_file.download_to_drive(custom_path=str(destination))


def ffmpeg_run(args: List[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
        raise RuntimeError(err[-1200:])


def convert_image_to_webp(src: Path, dst: Path) -> None:
    sizes = [512, 480, 448, 420, 384, 360]
    qualities = [100, 95, 90, 85, 80, 75, 70, 65, 60]
    for size in sizes:
        for q in qualities:
            vf = (
                f"scale='if(gt(a,1),{size},-2)':'if(gt(a,1),-2,{size})':force_original_aspect_ratio=decrease,"
                f"pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,format=rgba"
            )
            args = [
                "ffmpeg", "-y", "-i", str(src),
                "-vf", vf,
                "-vcodec", "libwebp",
                "-lossless", "0",
                "-q:v", str(q),
                "-preset", "picture",
                "-an",
                str(dst),
            ]
            try:
                ffmpeg_run(args)
            except Exception:
                continue
            if dst.exists() and dst.stat().st_size <= 512 * 1024:
                return
    raise RuntimeError("الصورة طلعت كبيرة أكثر من المسموح، جرّب صورة أخف")


def convert_video_to_webm(src: Path, dst: Path) -> None:
    sizes = [512, 480, 448, 420, 384]
    crfs = [32, 34, 36, 38, 40, 42, 44]
    for size in sizes:
        for crf in crfs:
            vf = (
                f"fps=30,scale='if(gt(a,1),{size},-2)':'if(gt(a,1),-2,{size})':force_original_aspect_ratio=decrease,"
                f"pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p"
            )
            args = [
                "ffmpeg", "-y", "-i", str(src),
                "-t", "3",
                "-an",
                "-vf", vf,
                "-c:v", "libvpx-vp9",
                "-b:v", "0",
                "-crf", str(crf),
                "-deadline", "good",
                "-cpu-used", "6",
                str(dst),
            ]
            try:
                ffmpeg_run(args)
            except Exception:
                continue
            if dst.exists() and dst.stat().st_size <= 256 * 1024:
                return
    raise RuntimeError("الفيديو بعد الضغط بقي أكبر من الحد المسموح")


def pack_limit(kind: str) -> int:
    return LIMIT_PER_PACK


def get_packs(user_id: int, kind: Optional[str] = None) -> List[sqlite3.Row]:
    if kind:
        return db_all(
            "SELECT * FROM packs WHERE user_id = ? AND kind = ? ORDER BY active DESC, id ASC",
            (user_id, kind),
        )
    return db_all(
        "SELECT * FROM packs WHERE user_id = ? ORDER BY kind, active DESC, id ASC",
        (user_id,),
    )


def get_pack(pack_id: int) -> Optional[sqlite3.Row]:
    return db_one("SELECT * FROM packs WHERE id = ?", (pack_id,))


def get_pack_by_name(short_name: str) -> Optional[sqlite3.Row]:
    return db_one("SELECT * FROM packs WHERE short_name = ?", (short_name,))


def get_active_pack(user_id: int, kind: str) -> Optional[sqlite3.Row]:
    return db_one(
        "SELECT * FROM packs WHERE user_id = ? AND kind = ? AND active = 1 ORDER BY id DESC LIMIT 1",
        (user_id, kind),
    )


def set_active_pack(user_id: int, pack_id: int) -> None:
    pack = get_pack(pack_id)
    if not pack:
        return
    db_execute("UPDATE packs SET active = 0 WHERE user_id = ? AND kind = ?", (user_id, pack["kind"]))
    db_execute("UPDATE packs SET active = 1 WHERE id = ?", (pack_id,))


def update_pack_count(pack_id: int, delta: int) -> None:
    db_execute("UPDATE packs SET sticker_count = MAX(sticker_count + ?, 0) WHERE id = ?", (delta, pack_id))


def add_sticker_record(user_id: int, pack_id: int, file_id: str, emoji: str, keywords: Optional[str] = None) -> None:
    with DB_LOCK:
        conn.execute(
            "INSERT INTO stickers(user_id, pack_id, file_id, emoji, keywords) VALUES(?,?,?,?,?)",
            (user_id, pack_id, file_id, emoji, keywords),
        )
        conn.commit()


def get_last_sticker(pack_id: int) -> Optional[sqlite3.Row]:
    return db_one(
        "SELECT * FROM stickers WHERE pack_id = ? ORDER BY id DESC LIMIT 1",
        (pack_id,),
    )


def delete_last_sticker_record(pack_id: int) -> None:
    db_execute(
        "DELETE FROM stickers WHERE id = (SELECT id FROM stickers WHERE pack_id = ? ORDER BY id DESC LIMIT 1)",
        (pack_id,),
    )


def delete_pack_records(pack_id: int) -> None:
    with DB_LOCK:
        conn.execute("DELETE FROM stickers WHERE pack_id = ?", (pack_id,))
        conn.execute("DELETE FROM packs WHERE id = ?", (pack_id,))
        conn.commit()


def emojis_from_text(text: str) -> List[str]:
    return [p for p in text.replace(",", " ").split() if p.strip()]


def is_name_conflict(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(x in s for x in ["occupied", "already exists", "name is invalid", "short name"])


async def send_or_edit(query, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
    except TelegramError:
        await query.message.reply_text(text, reply_markup=reply_markup, disable_web_page_preview=True)


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📦 حزماتي", callback_data="menu:packs"),
                InlineKeyboardButton("📊 الإحصائيات", callback_data="menu:stats"),
            ],
            [
                InlineKeyboardButton("🎨 الإيموجي الافتراضي", callback_data="menu:emoji"),
                InlineKeyboardButton("🆕 حزمة جديدة", callback_data="menu:newpack"),
            ],
            [InlineKeyboardButton("🆘 المساعدة", callback_data="menu:help")],
        ]
    )


def pending_kb(pending: Dict[str, Any]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"✅ إضافة ({pending.get('emoji') or DEFAULT_EMOJI})", callback_data="media:add"),
                InlineKeyboardButton("✏️ إيموجي", callback_data="media:custom"),
            ],
            [
                InlineKeyboardButton("📦 الحزمة", callback_data="media:pickpack"),
                InlineKeyboardButton("🆕 حزمة جديدة", callback_data="media:newpack"),
            ],
            [
                InlineKeyboardButton(COMMON_EMOJIS[0], callback_data="media:e:0"),
                InlineKeyboardButton(COMMON_EMOJIS[1], callback_data="media:e:1"),
                InlineKeyboardButton(COMMON_EMOJIS[2], callback_data="media:e:2"),
            ],
            [
                InlineKeyboardButton(COMMON_EMOJIS[3], callback_data="media:e:3"),
                InlineKeyboardButton(COMMON_EMOJIS[4], callback_data="media:e:4"),
                InlineKeyboardButton(COMMON_EMOJIS[5], callback_data="media:e:5"),
            ],
            [
                InlineKeyboardButton(COMMON_EMOJIS[6], callback_data="media:e:6"),
                InlineKeyboardButton(COMMON_EMOJIS[7], callback_data="media:e:7"),
            ],
            [InlineKeyboardButton("❌ إلغاء", callback_data="media:cancel")],
        ]
    )


def pack_list_kb(user_id: int, kind: Optional[str] = None, pending_mode: bool = False) -> InlineKeyboardMarkup:
    packs = get_packs(user_id, kind)
    rows: List[List[InlineKeyboardButton]] = []
    for pack in packs[:20]:
        label = f"{pack['title']} · {pack['sticker_count']}"
        if pending_mode:
            rows.append([InlineKeyboardButton(label, callback_data=f"pickpack:{pack['id']}")])
        else:
            rows.append([InlineKeyboardButton(label, callback_data=f"pack:{pack['id']}:menu")])
    if pending_mode:
        rows.append([InlineKeyboardButton("🆕 حزمة جديدة", callback_data="media:newpack")])
        rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data="media:back")])
    else:
        rows.append([InlineKeyboardButton("⬅️ الرئيسية", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def pack_action_kb(pack_id: int, short_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔗 الرابط", url=f"https://t.me/addstickers/{short_name}"),
                InlineKeyboardButton("⭐ نشطة", callback_data=f"pack:{pack_id}:active"),
            ],
            [
                InlineKeyboardButton("✏️ إعادة تسمية", callback_data=f"pack:{pack_id}:rename"),
                InlineKeyboardButton("🏷 إيموجي آخر", callback_data=f"pack:{pack_id}:emoji"),
            ],
            [
                InlineKeyboardButton("🔍 كلمات آخر", callback_data=f"pack:{pack_id}:keywords"),
                InlineKeyboardButton("🗑 حذف آخر", callback_data=f"pack:{pack_id}:dellastask"),
            ],
            [
                InlineKeyboardButton("🚮 حذف الحزمة", callback_data=f"pack:{pack_id}:delpackask"),
                InlineKeyboardButton("⬅️ رجوع", callback_data="menu:packs"),
            ],
        ]
    )


def confirm_kb(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ نعم", callback_data=yes_cb), InlineKeyboardButton("❌ لا", callback_data=no_cb)]]
    )


async def show_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ensure_user(update.effective_user.id)
    user = get_user(update.effective_user.id)
    text = (
        "هلا بيك 👋\n\n"
        f"الإيموجي الافتراضي الحالي: {user['default_emoji']}\n"
        "أرسل صورة أو فيديو أو GIF أو ملف مدعوم، وأنا أجهزه ستيكر وأحطه بالحزمة.\n\n"
        "المزايا الحالية:\n"
        "• اختيار إيموجي سريع أو مخصص\n"
        "• حزم متعددة وتنظيمها\n"
        "• إعادة تسمية عنوان الحزمة\n"
        "• حذف آخر ستكر أو حذف الحزمة كاملة\n"
        "• تعديل إيموجي/كلمات آخر ستكر\n"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=main_menu_kb())
    else:
        await update.effective_chat.send_message(text, reply_markup=main_menu_kb())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_main(update, context)


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_main(update, context)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "طريقة الاستخدام:\n"
        "1) أرسل صورة أو فيديو.\n"
        "2) اختَر الإيموجي والحزمة من الأزرار.\n"
        "3) اضغط إضافة.\n\n"
        "أوامر مفيدة:\n"
        "/packs - عرض الحزم\n"
        "/stats - الإحصائيات\n"
        "/emoji - تغيير الإيموجي الافتراضي\n"
        "/cancel - إلغاء العملية الحالية\n\n"
        "ملاحظة: إعادة التسمية هنا تغيّر عنوان الحزمة الظاهر فقط."
    )
    await update.effective_message.reply_text(text, reply_markup=main_menu_kb())


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    row = db_one(
        "SELECT "
        "(SELECT COUNT(*) FROM packs WHERE user_id = ?) AS pack_count, "
        "(SELECT COUNT(*) FROM stickers WHERE user_id = ?) AS sticker_count",
        (update.effective_user.id, update.effective_user.id),
    )
    text = (
        "📊 الإحصائيات\n\n"
        f"عدد الحزم: {row['pack_count']}\n"
        f"عدد الستيكرات: {row['sticker_count']}\n"
        f"الإيموجي الافتراضي: {user['default_emoji']}\n"
    )
    await update.effective_message.reply_text(text, reply_markup=main_menu_kb())


async def packs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    packs = get_packs(update.effective_user.id)
    if not packs:
        await update.effective_message.reply_text("ما عندك حزم بعد.", reply_markup=main_menu_kb())
        return

    lines = ["📦 حزمك:\n"]
    for p in packs:
        active = "⭐" if p["active"] else "•"
        lines.append(f"{active} {p['title']} ({kind_label(p['kind'])}) - {p['sticker_count']}")

    await update.effective_message.reply_text("\n".join(lines), reply_markup=pack_list_kb(update.effective_user.id))


async def emoji_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["awaiting"] = "default_emoji"
    await update.effective_message.reply_text(
        "أرسل الإيموجي الافتراضي الجديد الآن.\n"
        "ممكن واحد أو أكثر، بس خلّه مختصر.",
        reply_markup=main_menu_kb(),
    )


async def newpack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = context.user_data.get("pending")
    if not pending:
        await update.effective_message.reply_text(
            "حتى أسوي حزمة جديدة لازم أولاً ترسل صورة أو فيديو حتى أبدأ منها.",
            reply_markup=main_menu_kb(),
        )
        return
    pending["force_new_pack"] = True
    context.user_data["pending"] = pending
    await refresh_pending_prompt(update.effective_chat.id, context, note="تم اختيار: إنشاء حزمة جديدة لهذه القطعة.")


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clear_pending(context)
    context.user_data.pop("awaiting", None)
    context.user_data.pop("selected_pack_id", None)
    await update.effective_message.reply_text("تم الإلغاء ✅", reply_markup=main_menu_kb())


async def clear_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = context.user_data.pop("pending", None)
    if pending:
        workdir = pending.get("workdir")
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)


async def set_bot_default_emoji_from_text(user_id: int, emoji_text: str) -> None:
    em = emojis_from_text(emoji_text)
    if not em:
        raise ValueError("أرسل إيموجي واحد على الأقل")
    set_user_default_emoji(user_id, " ".join(em[:3]))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    awaiting = context.user_data.get("awaiting")
    if awaiting == "default_emoji":
        try:
            await set_bot_default_emoji_from_text(update.effective_user.id, text)
            context.user_data.pop("awaiting", None)
            await update.effective_message.reply_text("تم تغيير الإيموجي ✅")
        except Exception as e:
            await update.effective_message.reply_text(f"خطأ: {e}")

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    ensure_user(user_id)
    kind = kind_from_message(update.message)
    if not kind: return
    workdir = make_workdir(user_id)
    src_path = workdir / "source"
    await download_media(update.message, src_path)
    user = get_user(user_id)
    context.user_data["pending"] = {
        "user_id": user_id, "kind": kind, "workdir": workdir,
        "src_path": src_path, "emoji": user["default_emoji"]
    }
    await update.message.reply_text(f"وصلتني {kind_label(kind)}!", reply_markup=pending_kb(context.user_data["pending"]))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    await query.answer()
    if data == "cancel_pending":
        await clear_pending(context)
        await query.edit_message_text("تم الإلغاء ❌")
    elif data == "new_pack":
        context.user_data["awaiting"] = "pack_title"
        await query.edit_message_text("أرسل اسماً للحزمة الجديدة:")
    elif data.startswith("add_to_"):
        await query.edit_message_text("جاري الإضافة... ⏳")
        # هنا تكملة المعالجة

def setup_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    media_filter = filters.ChatType.PRIVATE & (filters.PHOTO | filters.VIDEO | filters.ANIMATION)
    app.add_handler(MessageHandler(media_filter, handle_media))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text))

async def post_init(app):
    init_db()
    me = await app.bot.get_me()
    log.info(f"=== {me.username} اشتغل! ===")

def main() -> None:
    if not TOKEN: return
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    setup_handlers(app)
    app.run_polling()

if __name__ == "__main__":
    main()
    
