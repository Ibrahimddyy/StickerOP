import os
import logging
from PIL import Image

# إعداد السجلات (Logs) لرؤية ما يحدث داخل Railway
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# حل مشكلة ANTIALIAS الجذري
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = getattr(Image, 'LANCZOS', 1)

try:
    from moviepy.editor import VideoFileClip
except ImportError:
    try: from moviepy import VideoFileClip
    except ImportError: from moviepy.video.io.VideoFileClip import VideoFileClip

from telegram import Update, ReplyKeyboardMarkup, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
user_data = {}

def main_keyboard():
    return ReplyKeyboardMarkup([
        ["📸 تحويل صورة", "🎥 تحويل فيديو"],
        ["📦 إنشاء حزمة جديدة", "🗂️ حزمي الحالية"]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id] = {"pack_name": None, "mode": None}
    logger.info(f"User {user_id} started the bot")
    await update.message.reply_text(
        "🚀 أهلاً بك! البوت يعمل الآن بنظام الاستقرار.\n"
        "1. اضغط 'إنشاء حزمة' أولاً.\n"
        "2. اختر نوع التحويل.\n"
        "3. أرسل ملفك.",
        reply_markup=main_keyboard()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if user_id not in user_data: user_data[user_id] = {}

    if text == "📸 تحويل صورة":
        user_data[user_id]["mode"] = "photo"
        await update.message.reply_text("📥 أرسل الصورة الآن...")
    elif text == "🎥 تحويل فيديو":
        user_data[user_id]["mode"] = "video"
        await update.message.reply_text("📥 أرسل الفيديو (أقل من 3 ثوانٍ)...")
    elif text == "📦 إنشاء حزمة جديدة":
        user_data[user_id]["waiting_for_name"] = True
        await update.message.reply_text("✍️ أرسل اسماً للحزمة (بالإنجليزي فقط):")
    elif user_data[user_id].get("waiting_for_name"):
        clean_name = "".join(e for e in text if e.isalnum())
        bot_info = await context.bot.get_me()
        user_data[user_id]["pack_name"] = f"st_{user_id}_{clean_name}_by_{bot_info.username}"
        user_data[user_id]["waiting_for_name"] = False
        await update.message.reply_text(f"✅ تم تفعيل الحزمة: {text}")
    elif text == "🗂️ حزمي الحالية":
        pack = user_data[user_id].get("pack_name")
        await update.message.reply_text(f"🔗 رابط حزمتك:\nt.me/addstickers/{pack}" if pack else "⚠️ لم تنشئ حزمة بعد.")

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = user_data.get(user_id, {}).get("mode")
    
    # إذا أرسل المستخدم ميديا بدون اختيار النوع، نفترض حسب نوع الملف
    if not mode:
        mode = "photo" if update.message.photo else "video"

    file_prefix = f"tmp_{user_id}"
    out_path = ""

    try:
        status_msg = await update.message.reply_text("⏳ جاري المعالجة...")
        
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            await file.download_to_drive(f"{file_prefix}.jpg")
            img = Image.open(f"{file_prefix}.jpg").convert("RGBA")
            img.thumbnail((512, 512), Image.ANTIALIAS)
            out_path = f"{user_id}.webp"
            img.save(out_path, "WEBP")
            stk_type = "static"
        
        elif update.message.video or update.message.video_note:
            media = update.message.video or update.message.video_note
            file = await media.get_file()
            await file.download_to_drive(f"{file_prefix}.mp4")
            clip = VideoFileClip(f"{file_prefix}.mp4")
            duration = min(2.9, clip.duration)
            try: clip = clip.subclip(0, duration)
            except: clip = clip.cropped(0, duration)
            
            w, h = clip.size
            if w > h: clip = clip.resize(width=512)
            else: clip = clip.resize(height=512)
            
            out_path = f"{user_id}.webm"
            clip.write_videofile(out_path, codec="libvpx-vp9", fps=30, bitrate="400k", audio=False, logger=None, ffmpeg_params=["-pix_fmt", "yuva420p"])
            clip.close()
            stk_type = "video"

        with open(out_path, "rb") as f:
            await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=f)

        # نظام الحزم المتوافق مع كل النسخ
        pack_name = user_data[user_id].get("pack_name")
        if pack_name:
            with open(out_path, "rb") as f:
                try:
                    # الطريقة الحديثة
                    stk = InputSticker(sticker=f, emoji_list=["✨"], format=stk_type)
                    await context.bot.add_sticker_to_set(user_id=user_id, name=pack_name, sticker=stk)
                except:
                    try:
                        # الطريقة الوسطى
                        stk = InputSticker(sticker=f, emoji_list=["✨"])
                        await context.bot.add_sticker_to_set(user_id=user_id, name=pack_name, stickers=[stk])
                    except:
                        # طريقة الإنشاء لأول مرة
                        await context.bot.create_new_sticker_set(
                            user_id=user_id, name=pack_name, title="My Pack", 
                            stickers=[InputSticker(sticker=open(out_path, "rb"), emoji_list=["✨"])])
                await update.message.reply_text("✅ تمت الإضافة للحزمة!")

    except Exception as e:
        logger.error(f"Error in handle_media: {e}")
        await update.message.reply_text(f"❌ خطأ: {str(e)}")
    finally:
        for f in [f"{file_prefix}.jpg", f"{file_prefix}.mp4", out_path]:
            if os.path.exists(f): os.remove(f)

if __name__ == '__main__':
    if not TOKEN:
        print("❌ Error: BOT_TOKEN variable is missing!")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE, handle_media))
        print("✅ Bot is running...")
        app.run_polling(drop_pending_updates=True)
        
