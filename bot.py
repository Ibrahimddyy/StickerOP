import os, logging, uuid
from PIL import Image
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import StickerFormat

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from moviepy.editor import VideoFileClip
except:
    from moviepy.video.io.VideoFileClip import VideoFileClip

TOKEN = os.getenv("BOT_TOKEN")

# --- الواجهة ---
def main_menu():
    return ReplyKeyboardMarkup([
        ["📸 تحويل صورة", "🎥 تحويل فيديو / GIF"],
        ["📦 إنشاء حزمة جديدة", "➕ إضافة حزمة"],
        ["🗂️ حزمي"]
    ], resize_keyboard=True)

# --- البداية ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🚀 جاهز! أرسل صورة أو فيديو", reply_markup=main_menu())

# --- النصوص ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    state = context.user_data.get("state")

    if text == "📸 تحويل صورة":
        context.user_data["state"] = "wait_media"
        await update.message.reply_text("📥 أرسل الصورة")

    elif text == "🎥 تحويل فيديو / GIF":
        context.user_data["state"] = "wait_media"
        await update.message.reply_text("📥 أرسل الفيديو أو GIF")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = "wait_title"
        await update.message.reply_text("✍️ اكتب اسم الحزمة")

    elif text == "➕ إضافة حزمة":
        context.user_data["state"] = "add_pack"
        await update.message.reply_text("📎 أرسل اسم الحزمة (آخر الرابط)")

    elif text == "🗂️ حزمي":
        packs = context.user_data.get("packs", [])
        await update.message.reply_text("\n".join(packs) if packs else "ماكو حزم")

    elif state == "wait_title":
        context.user_data["title"] = text
        context.user_data["state"] = "wait_name"
        await update.message.reply_text("🔗 اكتب اسم الرابط بالانكليزي")

    elif state == "wait_name":
        clean = "".join(e for e in text if e.isalnum())
        context.user_data["name"] = clean
        context.user_data["state"] = "first_sticker"
        await update.message.reply_text("📥 أرسل أول ملصق")

    elif state == "add_pack":
        packs = context.user_data.setdefault("packs", [])
        packs.append(text)
        context.user_data["state"] = None
        await update.message.reply_text("✅ تم إضافة الحزمة", reply_markup=main_menu())

    elif state == "wait_emoji":
        emoji = text if len(text) <= 2 else "😀"
        context.user_data["emoji"] = emoji

        packs = context.user_data.get("packs", [])
        if not packs:
            await update.message.reply_text("⚠️ ماكو حزم")
            return

        btns = [[KeyboardButton(p)] for p in packs]
        context.user_data["state"] = "choose_pack"
        await update.message.reply_text("اختر الحزمة:", reply_markup=ReplyKeyboardMarkup(btns, resize_keyboard=True))

    elif state == "choose_pack":
        await add_sticker(update, context, text)

# --- الميديا ---
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    file = None
    is_video = False

    if msg.photo:
        file = await msg.photo[-1].get_file()
        raw = f"{uuid.uuid4().hex}.jpg"
    else:
        file = await (msg.video or msg.animation).get_file()
        raw = f"{uuid.uuid4().hex}.mp4"
        is_video = True

    await file.download_to_drive(raw)

    out, s_type = process_media(raw, is_video)

    context.user_data["file"] = out
    context.user_data["emoji"] = "😀"

    if context.user_data.get("state") == "first_sticker":
        await create_pack(update, context, s_type)
    else:
        context.user_data["state"] = "wait_emoji"
        with open(out, "rb") as f:
            await context.bot.send_sticker(update.effective_user.id, f)
        await update.message.reply_text("😀 أرسل الإيموجي")

# --- المعالجة ---
def process_media(path, is_video):
    if not is_video:
        out = path.replace(".jpg", ".webp")
        img = Image.open(path).convert("RGBA")

        # 🔥 تحسين الجودة
        img.thumbnail((512, 512), Image.LANCZOS)

        img.save(out, "WEBP", quality=100, method=6)
        return out, StickerFormat.STATIC

    else:
        out = path.replace(".mp4", ".webm")

        clip = VideoFileClip(path).subclip(0, min(3, VideoFileClip(path).duration))

        clip = clip.resize(width=512)

        clip.write_videofile(
            out,
            codec="libvpx-vp9",
            fps=30,
            bitrate="250k",
            audio=False,
            logger=None,
            ffmpeg_params=['-pix_fmt', 'yuva420p']
        )

        clip.close()
        return out, StickerFormat.VIDEO

# --- إنشاء حزمة ---
async def create_pack(update, context, s_type):
    user = update.effective_user.id
    bot = await context.bot.get_me()

    name = f"st_{context.user_data['name']}_{uuid.uuid4().hex[:4]}_{user}_by_{bot.username}"
    title = context.user_data["title"]

    try:
        with open(context.user_data["file"], "rb") as f:
            await context.bot.create_new_sticker_set(
                user_id=user,
                name=name,
                title=title,
                stickers=[InputSticker(f, [context.user_data["emoji"]])],
                sticker_format=s_type
            )

        context.user_data.setdefault("packs", []).append(name)

        await update.message.reply_text(f"🎉 تم الإنشاء:\nhttps://t.me/addstickers/{name}", reply_markup=main_menu())

    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

# --- إضافة ملصق ---
async def add_sticker(update, context, pack):
    try:
        with open(context.user_data["file"], "rb") as f:
            await context.bot.add_sticker_to_set(
                user_id=update.effective_user.id,
                name=pack,
                sticker=InputSticker(f, [context.user_data["emoji"]])
            )

        await update.message.reply_text("✅ تمت الإضافة", reply_markup=main_menu())

    except Exception as e:
        await update.message.reply_text(f"❌ فشل: {e}")

# --- تشغيل ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.ALL, handle_media))

    app.run_polling()
