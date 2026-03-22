import os
import telegram
from PIL import Image

# حل مشكلة ANTIALIAS للنسخ الجديدة والقديمة
try:
    from PIL.Image import Resampling
    LANCZOS = Resampling.LANCZOS
except ImportError:
    LANCZOS = Image.ANTIALIAS

# حل مشكلة استيراد MoviePy مهما كان إصدارها
try:
    from moviepy.editor import VideoFileClip
except ImportError:
    try:
        from moviepy import VideoFileClip
    except ImportError:
        from moviepy.video.io.VideoFileClip import VideoFileClip

from telegram import Update, ReplyKeyboardMarkup, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
user_packs = {} 
temp = {}

def keyboard():
    return ReplyKeyboardMarkup(
        [["📸 صورة", "🎥 فيديو"], ["📦 انشاء حزمة", "🗂️ حزمي"]],
        resize_keyboard=True
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 البوت عاد للعمل! أرسل /start إذا توقفت القائمة.", reply_markup=keyboard())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    text = update.message.text
    if user_id not in temp: temp[user_id] = {}

    if text == "📸 صورة":
        temp[user_id]["mode"] = "photo"
        await update.message.reply_text("أرسل الصورة الآن")
    elif text == "🎥 فيديو":
        temp[user_id]["mode"] = "video"
        await update.message.reply_text("أرسل الفيديو الآن")
    elif text == "📦 انشاء حزمة":
        temp[user_id]["create_pack"] = True
        await update.message.reply_text("أرسل اسم الحزمة بالإنجليزية")
    elif temp[user_id].get("create_pack"):
        bot_info = await context.bot.get_me()
        clean_name = "".join(e for e in text if e.isalnum())
        pack_id = f"s_{user_id}_{clean_name}_by_{bot_info.username}"
        user_packs[user_id] = pack_id
        temp[user_id]["create_pack"] = False
        await update.message.reply_text(f"✅ تم تفعيل الحزمة: {text}")
    elif temp[user_id].get("wait"):
        temp[user_id]["emoji"] = text
        temp[user_id]["wait"] = False
        await process(update, context, user_id)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if temp.get(user_id, {}).get("mode") != "photo": return
    file = await update.message.photo[-1].get_file()
    path = f"{user_id}.jpg"
    await file.download_to_drive(path)
    temp[user_id]["file"] = path
    temp[user_id]["video"] = False
    temp[user_id]["wait"] = True
    await update.message.reply_text("أرسل ايموجي للستيكر")

async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if temp.get(user_id, {}).get("mode") != "video": return
    file = await update.message.video.get_file()
    path = f"{user_id}.mp4"
    await file.download_to_drive(path)
    temp[user_id]["file"] = path
    temp[user_id]["video"] = True
    temp[user_id]["wait"] = True
    await update.message.reply_text("أرسل ايموجي للستيكر")

async def process(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    data = temp[user_id]
    path = data["file"]
    emoji = data.get("emoji", "✨")
    out = ""
    try:
        if data.get("video"):
            clip = VideoFileClip(path)
            # التأكد من عمل subclip في كل الإصدارات
            duration = min(2.9, clip.duration)
            clip = clip.subclip(0, duration)
            
            w, h = clip.size
            if w > h: clip = clip.resize(width=512)
            else: clip = clip.resize(height=512)
            
            out = f"{user_id}.webm"
            clip.write_videofile(
                out, codec="libvpx-vp9", fps=30, bitrate="300k", 
                audio=False, logger=None, ffmpeg_params=["-pix_fmt", "yuva420p"]
            )
            clip.close()
            sticker_format = "video"
        else:
            img = Image.open(path).convert("RGBA")
            img = img.resize((512, 512), LANCZOS)
            out = f"{user_id}.webp"
            img.save(out, "WEBP")
            sticker_format = "static"

        with open(out, "rb") as f:
            await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=f)

        pack_name = user_packs.get(user_id)
        if pack_name:
            with open(out, "rb") as f:
                # محاولة الإضافة بطريقة متوافقة مع إصدارات المكتبة المختلفة
                try:
                    sticker_obj = InputSticker(sticker=f, emoji_list=[emoji])
                    await context.bot.add_sticker_to_set(user_id=int(user_id), name=pack_name, sticker=sticker_obj)
                except Exception:
                    # إذا كانت الحزمة غير موجودة، ننشئها
                    await context.bot.create_new_sticker_set(
                        user_id=int(user_id), name=pack_name, title="My Pack", 
                        stickers=[InputSticker(sticker=open(out, "rb"), emoji_list=[emoji])],
                        sticker_format=sticker_format
                    )
                await update.message.reply_text("✅ تمت الإضافة بنجاح!")

    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")
    finally:
        if os.path.exists(path): os.remove(path)
        if out and os.path.exists(out): os.remove(out)
        temp[user_id] = {}

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.VIDEO, video_handler))
    app.run_polling()
    
