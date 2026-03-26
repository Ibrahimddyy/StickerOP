import os
import json
import uuid
import asyncio
import logging
from pathlib import Path

from PIL import Image, ImageOps
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputSticker,
)
from telegram.constants import StickerFormat
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

try:
    from moviepy.editor import VideoFileClip
except Exception:
    try:
        from moviepy import VideoFileClip
    except Exception:
        from moviepy.video.io.VideoFileClip import VideoFileClip

TOKEN = os.getenv("BOT_TOKEN")
STORE_FILE = "sticker_packs_store.json"

STATE_NEW_PACK_TITLE = "new_pack_title"
STATE_NEW_PACK_NAME = "new_pack_name"
STATE_NEW_PACK_EMOJI = "new_pack_emoji"
STATE_ADD_STICKER_EMOJI = "add_sticker_emoji"
STATE_ADD_PACK_MANUAL = "add_pack_manual"

# -------------------- التخزين --------------------

def load_store():
    if not os.path.exists(STORE_FILE):
        return {}
    try:
        with open(STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_store(data):
    tmp = f"{STORE_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE_FILE)

PACKS_STORE = load_store()

def get_user_packs(user_id: int):
    return PACKS_STORE.get(str(user_id), [])

def add_user_pack(user_id: int, name: str, title: str):
    key = str(user_id)
    packs = PACKS_STORE.setdefault(key, [])
    if not any(p["name"] == name for p in packs):
        packs.append({"name": name, "title": title})
        save_store(PACKS_STORE)

def normalize_pack_ref(text: str) -> str:
    text = text.strip()

    if "addstickers/" in text:
        text = text.split("addstickers/", 1)[1]

    text = text.replace("https://", "").replace("http://", "")
    text = text.replace("t.me/", "")
    text = text.replace("@", "")
    text = text.split("?")[0].split("#")[0].strip()

    return text

def safe_slug(text: str) -> str:
    cleaned = "".join(ch for ch in text if ch.isalnum())
    return cleaned[:12] if cleaned else "pack"

# -------------------- الواجهة --------------------

def main_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📸 تحويل صورة"), KeyboardButton("🎥 تحويل فيديو / GIF")],
            [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("➕ إضافة حزمة")],
            [KeyboardButton("🗂️ حزمي")]
        ],
        resize_keyboard=True
    )

def pack_selection_keyboard(user_id: int):
    packs = get_user_packs(user_id)

    rows = []
    for p in packs:
        label = p.get("title") or p["name"]
        rows.append([InlineKeyboardButton(label, callback_data=f"usepack|{p['name']}")])

    rows.append([
        InlineKeyboardButton("➕ إضافة حزمة", callback_data="manual_add_pack"),
        InlineKeyboardButton("📦 إنشاء حزمة جديدة", callback_data="new_pack_flow"),
    ])

    return InlineKeyboardMarkup(rows)

# -------------------- أدوات مساعدة --------------------

def cleanup_path(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

async def reply_sticker_preview(context: ContextTypes.DEFAULT_TYPE, chat_id: int, path: str):
    with open(path, "rb") as f:
        await context.bot.send_sticker(chat_id=chat_id, sticker=f)

def process_media_sync(raw_path: str, is_video: bool):
    out_path = f"out_{uuid.uuid4().hex[:8]}" + (".webm" if is_video else ".webp")

    if not is_video:
        img = Image.open(raw_path)
        img = ImageOps.exif_transpose(img).convert("RGBA")

        # تحسين الجودة: نحتفظ بالشكل ونضعه بمنتصف لوحة 512x512 شفافة
        contained = ImageOps.contain(img, (512, 512), Image.LANCZOS)
        canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        x = (512 - contained.width) // 2
        y = (512 - contained.height) // 2
        canvas.paste(contained, (x, y), contained)

        canvas.save(out_path, "WEBP", lossless=True, quality=100, method=6)
        return out_path, StickerFormat.STATIC

    clip = None
    try:
        clip = VideoFileClip(raw_path)
        duration = clip.duration or 3.0
        clip = clip.subclip(0, min(3.0, duration))

        if clip.w >= clip.h:
            clip = clip.resize(width=512)
        else:
            clip = clip.resize(height=512)

        clip.write_videofile(
            out_path,
            codec="libvpx-vp9",
            fps=30,
            bitrate="250k",
            audio=False,
            logger=None,
            ffmpeg_params=["-pix_fmt", "yuva420p"],
        )
        return out_path, StickerFormat.VIDEO
    finally:
        try:
            if clip is not None:
                clip.close()
        except Exception:
            pass

async def verify_pack_exists(context: ContextTypes.DEFAULT_TYPE, pack_ref: str):
    pack_name = normalize_pack_ref(pack_ref)
    if not pack_name:
        return None, "❌ اسم الحزمة فارغ."

    try:
        pack = await context.bot.get_sticker_set(pack_name)
        title = getattr(pack, "title", pack_name)
        return {"name": pack_name, "title": title}, None
    except Exception as e:
        return None, f"❌ ما كدرت أوصل للحزمة. تأكد من الاسم القصير فقط.\n{e}"

async def create_pack_from_pending(update: Update, context: ContextTypes.DEFAULT_TYPE, emoji: str):
    user_id = update.effective_user.id
    pending = context.user_data.get("pending_sticker")
    new_pack = context.user_data.get("new_pack")

    if not pending or not new_pack:
        await update.message.reply_text("⚠️ ماكو بيانات كافية لإنشاء الحزمة.")
        return

    bot_info = await context.bot.get_me()

    slug = safe_slug(new_pack.get("slug", "pack"))
    # اسم قصير وآمن لتجنب مشكلة الطول
    pack_name = f"st_{slug}_{uuid.uuid4().hex[:8]}_by_{bot_info.username}"

    title = new_pack.get("title", "Sticker Pack")

    try:
        with open(pending["path"], "rb") as f:
            stk = InputSticker(sticker=f, emoji_list=[emoji])

            await context.bot.create_new_sticker_set(
                user_id=user_id,
                name=pack_name,
                title=title,
                stickers=[stk],
                sticker_format=pending["format"],
            )

        add_user_pack(user_id, pack_name, title)

        await update.message.reply_text(
            f"🎉 تم إنشاء الحزمة بنجاح!\n"
            f"https://t.me/addstickers/{pack_name}",
            reply_markup=main_menu()
        )

    except Exception as e:
        await update.message.reply_text(f"❌ فشل إنشاء الحزمة:\n{e}")

    finally:
        cleanup_path(pending["path"])
        context.user_data.pop("pending_sticker", None)
        context.user_data.pop("new_pack", None)
        context.user_data.pop("state", None)

async def add_pending_to_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, pack_name: str):
    user_id = update.effective_user.id
    pending = context.user_data.get("pending_sticker")

    if not pending:
        await update.message.reply_text("⚠️ ماكو ملصق جاهز للإضافة.")
        return

    try:
        with open(pending["path"], "rb") as f:
            stk = InputSticker(sticker=f, emoji_list=[pending["emoji"]])

            await context.bot.add_sticker_to_set(
                user_id=user_id,
                name=pack_name,
                sticker=stk
            )

        await update.message.reply_text("✅ تمت إضافة الملصق بنجاح!", reply_markup=main_menu())

    except Exception as e:
        await update.message.reply_text(
            f"❌ فشل الإضافة:\n{e}\n\n"
            f"إذا كانت الحزمة نوعها مختلف عن نوع الملصق، تيليجرام يرفضها."
        )

    finally:
        cleanup_path(pending["path"])
        context.user_data.pop("pending_sticker", None)
        context.user_data.pop("state", None)

# -------------------- الأوامر والنصوص --------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("pending_sticker", None)
    context.user_data.pop("new_pack", None)
    context.user_data.pop("state", None)

    await update.message.reply_text(
        "🚀 أهلاً بك!\n"
        "أرسل صورة أو فيديو أو GIF، أو أنشئ حزمة جديدة من القائمة.",
        reply_markup=main_menu()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    state = context.user_data.get("state")
    user_id = update.effective_user.id

    if text == "📸 تحويل صورة":
        context.user_data["state"] = None
        await update.message.reply_text("📥 أرسل الصورة الآن.")

    elif text == "🎥 تحويل فيديو / GIF":
        context.user_data["state"] = None
        await update.message.reply_text("📥 أرسل الفيديو أو GIF الآن.")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = STATE_NEW_PACK_TITLE
        context.user_data.pop("pending_sticker", None)
        context.user_data.pop("new_pack", None)
        await update.message.reply_text("✍️ اكتب عنوان الحزمة بالعربي:")

    elif text == "➕ إضافة حزمة":
        context.user_data["state"] = STATE_ADD_PACK_MANUAL
        await update.message.reply_text("📎 أرسل رابط الحزمة أو اسمها القصير:")

    elif text == "🗂️ حزمي":
        packs = get_user_packs(user_id)
        if not packs:
            await update.message.reply_text("⚠️ ما عندك حزم محفوظة حالياً.")
        else:
            msg = "📚 حزمك المحفوظة:\n\n"
            msg += "\n".join([f"🔹 {p.get('title') or p['name']}\n   {p['name']}" for p in packs])
            await update.message.reply_text(msg)

    elif state == STATE_NEW_PACK_TITLE:
        context.user_data["new_pack"] = {
            "title": text,
            "slug": None
        }
        context.user_data["state"] = STATE_NEW_PACK_NAME
        await update.message.reply_text("🔗 اكتب اسم الرابط بالإنجليزي:")

    elif state == STATE_NEW_PACK_NAME:
        new_pack = context.user_data.get("new_pack", {})
        new_pack["slug"] = safe_slug(text)
        context.user_data["new_pack"] = new_pack
        context.user_data["state"] = None
        await update.message.reply_text("📥 أرسل أول ملصق الآن.")

    elif state == STATE_ADD_PACK_MANUAL:
        pack_ref = normalize_pack_ref(text)
        pack, err = await verify_pack_exists(context, pack_ref)
        if err:
            await update.message.reply_text(err)
            return

        add_user_pack(user_id, pack["name"], pack["title"])
        context.user_data["state"] = None
        await update.message.reply_text(
            f"✅ تم حفظ الحزمة:\n{pack['title']}\n\n"
            f"الآن أي ملصق تسويه راح تظهر لك هذه الحزمة ضمن الأزرار.",
            reply_markup=main_menu()
        )

    elif state == STATE_NEW_PACK_EMOJI:
        emoji = text if text else "😀"
        pending = context.user_data.get("pending_sticker")
        if pending:
            await create_pack_from_pending(update, context, emoji)
        else:
            await update.message.reply_text("⚠️ ماكو ملصق جاهز لإنشاء الحزمة.")

    elif state == STATE_ADD_STICKER_EMOJI:
        pending = context.user_data.get("pending_sticker")
        if not pending:
            await update.message.reply_text("⚠️ ماكو ملصق جاهز.")
            return

        pending["emoji"] = text if text else "😀"

        packs = get_user_packs(user_id)
        if not packs:
            await update.message.reply_text(
                "⚠️ ما عندك حزم محفوظة حالياً.\n"
                "اضغط (➕ إضافة حزمة) أو (📦 إنشاء حزمة جديدة).",
                reply_markup=main_menu()
            )
            return

        context.user_data["state"] = "choose_pack"
        await update.message.reply_text(
            "اختر الحزمة التي تريد الإضافة إليها:",
            reply_markup=pack_selection_keyboard(user_id)
        )

# -------------------- الميديا --------------------

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = update.effective_user.id
    state = context.user_data.get("state")

    # لا نعالج الميديا أثناء إدخال عنوان/اسم/إضافة رابط يدوي
    if state in {STATE_NEW_PACK_TITLE, STATE_NEW_PACK_NAME, STATE_ADD_PACK_MANUAL}:
        return

    media_obj = None
    is_video = False

    if msg.photo:
        media_obj = msg.photo[-1]
        raw_path = f"raw_{uuid.uuid4().hex[:8]}.jpg"
        is_video = False
    elif msg.video:
        media_obj = msg.video
        raw_path = f"raw_{uuid.uuid4().hex[:8]}.mp4"
        is_video = True
    elif msg.animation:
        media_obj = msg.animation
        raw_path = f"raw_{uuid.uuid4().hex[:8]}.mp4"
        is_video = True
    elif msg.video_note:
        media_obj = msg.video_note
        raw_path = f"raw_{uuid.uuid4().hex[:8]}.mp4"
        is_video = True
    else:
        return

    status = None
    out_path = None

    try:
        status = await update.message.reply_text("⏳ جاري التحويل...")

        file = await media_obj.get_file()
        await file.download_to_drive(raw_path)

        out_path, sticker_format = await asyncio.to_thread(
            process_media_sync, raw_path, is_video
        )

        context.user_data["pending_sticker"] = {
            "path": out_path,
            "format": sticker_format,
            "emoji": "😀",
        }

        # إذا هو داخل إنشاء حزمة جديدة، نخلي الخطوة الجاية هي الإيموجي ثم الإنشاء
        if state == STATE_NEW_PACK_NAME or state == STATE_NEW_PACK_EMOJI:
            context.user_data["state"] = STATE_NEW_PACK_EMOJI
        else:
            context.user_data["state"] = STATE_ADD_STICKER_EMOJI

        await reply_sticker_preview(context, user_id, out_path)
        await update.message.reply_text("😀 أرسل الإيموجي الخاص بهذا الملصق:")

    except Exception as e:
        logger.exception(e)
        await update.message.reply_text(f"❌ خطأ: {e}")

    finally:
        cleanup_path(raw_path)
        if status:
            try:
                await status.delete()
            except Exception:
                pass

# -------------------- الأزرار التفاعلية --------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = update.effective_user.id

    if data == "manual_add_pack":
        context.user_data["state"] = STATE_ADD_PACK_MANUAL
        await query.message.reply_text("📎 أرسل رابط الحزمة أو اسمها القصير:")

    elif data == "new_pack_flow":
        context.user_data["state"] = STATE_NEW_PACK_TITLE
        context.user_data.pop("pending_sticker", None)
        context.user_data.pop("new_pack", None)
        await query.message.reply_text("✍️ اكتب عنوان الحزمة بالعربي:")

    elif data.startswith("usepack|"):
        pack_name = data.split("|", 1)[1]

        pending = context.user_data.get("pending_sticker")
        if not pending:
            await query.message.reply_text("⚠️ ماكو ملصق جاهز للإضافة.")
            return

        await add_pending_to_pack(query, context, pack_name)

# -------------------- التشغيل --------------------

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))

    app.run_polling(drop_pending_updates=True)
