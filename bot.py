import os, logging, asyncio, uuid
from PIL import Image
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import StickerFormat

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from moviepy.editor import VideoFileClip
except:
    try: from moviepy import VideoFileClip
    except: from moviepy.video.io.VideoFileClip import VideoFileClip

TOKEN = os.getenv("BOT_TOKEN")

def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 تحويل صورة"), KeyboardButton("🎥 تحويل فيديو / GIF")],
        [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("🗂️ حزمي الحالية")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🚀 أهلاً بك! البوت يعمل بثبات الآن.\nأرسل صورتك أو فيديوك للبدء:",
        reply_markup=main_menu()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    state = context.user_data.get("state")

    if text == "📸 تحويل صورة":
        context.user_data.update({"mode": "photo", "state": "waiting_media"})
        await update.message.reply_text("📥 أرسل الصورة...")

    elif text == "🎥 تحويل فيديو / GIF":
        context.user_data.update({"mode": "video", "state": "waiting_media"})
        await update.message.reply_text("📥 أرسل الفيديو (أقل من 3 ثوانٍ)...")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = "waiting_title"
        await update.message.reply_text("✍️ أرسل عنوان الحزمة بالعربي:")

    elif text == "🗂️ حزمي الحالية":
        packs = context.user_data.get("my_packs_this_session", [])
        if not packs:
            await update.message.reply_text("⚠️ لا توجد حزم حالياً.")
        else:
            msg = "📚 حزمك:\n\n" + "\n".join([f"🔹 {p}" for p in packs])
            await update.message.reply_text(msg)

    elif state == "waiting_title":
        context.user_data.update({"temp_title": text, "state": "waiting_name"})
        await update.message.reply_text("🔗 أرسل اسم الرابط بالإنجليزي:")

    elif state == "waiting_name":
        clean_name = "".join(e for e in text if e.isalnum())
        context.user_data.update({"temp_name": clean_name, "state": "waiting_first_sticker"})
        await update.message.reply_text("✅ أرسل أول ملصق:")

    elif state == "waiting_emoji":
        if "last_sticker_info" in context.user_data:

            # 🔥 إصلاح الإيموجي
            emoji = text if len(text) <= 2 else "😀"
            context.user_data["last_sticker_info"]["emoji"] = emoji

            packs = context.user_data.get("my_packs_this_session", [])
            if not packs:
                await update.message.reply_text("💡 ماكو حزمة. سوي وحدة أولاً.")
                return
            else:
                context.user_data["state"] = "selecting_pack"
                btns = [[KeyboardButton(f"➕ إضافة إلى: {p}")] for p in packs]
                await update.message.reply_text("اختر الحزمة:", reply_markup=ReplyKeyboardMarkup(btns, resize_keyboard=True))

    elif text.startswith("➕ إضافة إلى: "):
        await add_to_existing_pack_action(update, context, text)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    media = msg.photo or msg.video or msg.animation or msg.video_note
    if not media: return

    try:
        status = await update.message.reply_text("⏳ جاري المعالجة...")
        file = await (media[-1].get_file() if msg.photo else media.get_file())

        raw_path = f"raw_{uuid.uuid4().hex[:4]}.mp4"
        await file.download_to_drive(raw_path)

        out_path, s_type = await process_media_core(raw_path)

        # 🔥 إيموجي ثابت مبدئياً
        context.user_data["last_sticker_info"] = {
            "path": out_path,
            "type": s_type,
            "emoji": "😀"
        }

        if context.user_data.get("state") == "waiting_first_sticker":
            await create_pack_action(update, context)
        else:
            context.user_data["state"] = "waiting_emoji"
            with open(out_path, "rb") as f:
                await context.bot.send_sticker(update.effective_user.id, f)
            await update.message.reply_text("😄 أرسل الإيموجي:")

        await status.delete()
        os.remove(raw_path)

    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ خطأ: {e}")

async def process_media_core(raw_path):
    is_video = raw_path.endswith(".mp4")

    out = f"out_{uuid.uuid4().hex[:4]}" + (".webm" if is_video else ".webp")

    if not is_video:
        img = Image.open(raw_path).convert("RGBA")
        img.thumbnail((512, 512), Image.LANCZOS)
        img.save(out, "WEBP")
        return out, StickerFormat.STATIC
    else:
        clip = VideoFileClip(raw_path).subclip(0, 2.5)
        clip = clip.resize(width=512)
        clip.write_videofile(
            out,
            codec="libvpx-vp9",
            fps=30,
            bitrate="180k",
            audio=False,
            logger=None,
            ffmpeg_params=['-pix_fmt', 'yuva420p']
        )
        clip.close()
        return out, StickerFormat.VIDEO

async def create_pack_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    info = context.user_data["last_sticker_info"]
    bot = await context.bot.get_me()

    clean_name = context.user_data["temp_name"]
    full_name = f"st_{clean_name}_{uuid.uuid4().hex[:4]}_{user_id}_by_{bot.username}"
    title = context.user_data["temp_title"]

    try:
        with open(info["path"], "rb") as f:
            stk = InputSticker(f, [info["emoji"]])

            await context.bot.create_new_sticker_set(
                user_id=user_id,
                name=full_name,
                title=title,
                stickers=[stk],
                sticker_format=info["type"]
            )

        # ✅ حفظ الحزم
        context.user_data.setdefault("my_packs_this_session", []).append(full_name)

        # 🔥 حفظ نوع الحزمة
        context.user_data.setdefault("packs_types", {})
        context.user_data["packs_types"][full_name] = info["type"]

        await update.message.reply_text(
            f"🎉 تم إنشاء الحزمة!\nhttps://t.me/addstickers/{full_name}",
            reply_markup=main_menu()
        )

    except Exception as e:
        await update.message.reply_text(f"❌ فشل: {e}")

async def add_to_existing_pack_action(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    info = context.user_data.get("last_sticker_info")
    pack_name = text.replace("➕ إضافة إلى: ", "")

    # 🔥 تحقق النوع
    pack_types = context.user_data.get("packs_types", {})
    if pack_types.get(pack_name) != info["type"]:
        await update.message.reply_text("❌ نوع الملصق مختلف عن الحزمة!")
        return

    try:
        with open(info["path"], "rb") as f:
            await context.bot.add_sticker_to_set(
                user_id=update.effective_user.id,
                name=pack_name,
                sticker=InputSticker(f, [info["emoji"]])
            )

        await update.message.reply_text("✅ تمت الإضافة!", reply_markup=main_menu())

    except Exception as e:
        await update.message.reply_text(f"❌ فشل: {e}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))
    app.run_polling()
