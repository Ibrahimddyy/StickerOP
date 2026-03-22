import os
import telegram
from PIL import Image

# حلول التوافق مع المكتبات (Pillow & MoviePy)
try:
    from PIL.Image import Resampling
    LANCZOS = Resampling.LANCZOS
except (ImportError, AttributeError):
    LANCZOS = getattr(Image, 'LANCZOS', getattr(Image, 'ANTIALIAS', None))

try:
    from moviepy.editor import VideoFileClip
except ImportError:
    try: from moviepy import VideoFileClip
    except ImportError: from moviepy.video.io.VideoFileClip import VideoFileClip

from telegram import Update, ReplyKeyboardMarkup, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

# مخزن البيانات (في بوت حقيقي يفضل استخدام قاعدة بيانات، هنا نستخدم الذاكرة)
user_data = {} 

def main_keyboard():
    return ReplyKeyboardMarkup([
        ["📸 تحويل صورة", "🎥 تحويل فيديو"],
        ["📦 إنشاء حزمة جديدة", "🗂️ حزمي الحالية"],
        ["📊 الإحصائيات", "⚙️ الإعدادات"]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data:
        user_data[user_id] = {"pack_name": None, "mode": None}
    
    await update.message.reply_text(
        "Welcome to Pro Sticker Bot 🚀\n\n"
        "البوت الآن يعمل بنظام الحزم الاحترافي. اختر ما تريد من القائمة أدناه:",
        reply_markup=main_keyboard()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id not in user_data: user_data[user_id] = {}

    if text == "📸 تحويل صورة":
        user_data[user_id]["mode"] = "photo"
        await update.message.reply_text("📥 أرسل الصورة الآن (سيتم تحويلها لستيكر ثابت)")
    
    elif text == "🎥 تحويل فيديو":
        user_data[user_id]["mode"] = "video"
        await update.message.reply_text("📥 أرسل الفيديو (يفضل أقل من 3 ثوانٍ)")

    elif text == "📦 إنشاء حزمة جديدة":
        user_data[user_id]["waiting_for_pack_name"] = True
        await update.message.reply_text("✍️ أرسل اسماً للحزمة (بالإنجليزي فقط وبدون مسافات):")

    elif user_data[user_id].get("waiting_for_pack_name"):
        clean_name = "".join(e for e in text if e.isalnum())
        bot_info = await context.bot.get_me()
        pack_id = f"st_{user_id}_{clean_name}_by_{bot_info.username}"
        user_data[user_id]["pack_name"] = pack_id
        user_data[user_id]["waiting_for_pack_name"] = False
        await update.message.reply_text(f"✅ تم اعتماد الحزمة: {text}\nأي ستيكر تصنعه الآن سيضاف إليها تلقائياً.")

    elif text == "🗂️ حزمي الحالية":
        pack = user_data[user_id].get("pack_name")
        if pack:
            await update.message.reply_text(f"حزمتك النشطة حالياً هي:\nt.me/addstickers/{pack}")
        else:
            await update.message.reply_text("لا توجد حزمة نشطة. اضغط على 'إنشاء حزمة' أولاً.")

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = user_data.get(user_id, {}).get("mode")
    
    if not mode:
        await update.message.reply_text("⚠️ من فضلك اختر 'صورة' أو 'فيديو' من القائمة أولاً.")
        return

    file_path = f"file_{user_id}"
    out_path = ""
    is_video = False

    try:
        msg = await update.message.reply_text("⏳ جاري المعالجة...")
        
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            await file.download_to_drive(f"{file_path}.jpg")
            img = Image.open(f"{file_path}.jpg").convert("RGBA")
            img.thumbnail((512, 512), LANCZOS)
            out_path = f"{user_id}.webp"
            img.save(out_path, "WEBP")
            sticker_format = "static"
        
        elif update.message.video or update.message.video_note:
            is_video = True
            media = update.message.video or update.message.video_note
            file = await media.get_file()
            await file.download_to_drive(f"{file_path}.mp4")
            
            clip = VideoFileClip(f"{file_path}.mp4")
            # قص الفيديو لـ 2.9 ثانية لضمان قبول تلغرام
            duration = min(2.9, clip.duration)
            try: clip = clip.subclip(0, duration)
            except: clip = clip.cropped(0, duration)
            
            # تغيير الحجم مع الحفاظ على التناسب
            w, h = clip.size
            if w > h: clip = clip.resized(width=512) if hasattr(clip, 'resized') else clip.resize(width=512)
            else: clip = clip.resized(height=512) if hasattr(clip, 'resized') else clip.resize(height=512)
            
            out_path = f"{user_id}.webm"
            clip.write_videofile(out_path, codec="libvpx-vp9", fps=30, bitrate="400k", audio=False, logger=None, ffmpeg_params=["-pix_fmt", "yuva420p"])
            clip.close()
            sticker_format = "video"

        # إرسال الستيكر للمستخدم
        with open(out_path, "rb") as f:
            await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=f)

        # إضافة الستيكر للحزمة (المكان الذي كان يحدث فيه الخطأ)
        pack_name = user_data[user_id].get("pack_name")
        if pack_name:
            with open(out_path, "rb") as f:
                sticker_obj = InputSticker(sticker=f, emoji_list=["✨"], format=sticker_format)
                try:
                    await context.bot.add_sticker_to_set(user_id=user_id, name=pack_name, sticker=sticker_obj)
                    await update.message.reply_text(f"✅ تمت إضافته للحزمة!")
                except Exception as e:
                    # إذا كانت أول مرة، ننشئ الحزمة
                    await context.bot.create_new_sticker_set(
                        user_id=user_id, name=pack_name, title="My Pro Pack", 
                        stickers=[sticker_obj], sticker_format=sticker_format
                    )
                    await update.message.reply_text(f"📦 تم إنشاء الحزمة وإضافة أول ستيكر!")

    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")
    finally:
        # تنظيف الملفات
        for f in [f"{file_path}.jpg", f"{file_path}.mp4", out_path]:
            if os.path.exists(f): os.remove(f)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE, handle_media))
    app.run_polling()
    
