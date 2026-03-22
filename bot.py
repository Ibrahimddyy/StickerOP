import os
import telegram
from PIL import Image

# --- معالجة توافق المكتبات ---
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

# مخزن بيانات المستخدمين (للحزم والحالات)
user_data = {}

def main_keyboard():
    return ReplyKeyboardMarkup([
        ["📸 تحويل صورة", "🎥 تحويل فيديو"],
        ["📦 إنشاء حزمة جديدة", "🗂️ حزمي الحالية"],
        ["📊 إحصائيات", "⚙️ الإعدادات"]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id] = {"pack_name": None, "mode": None}
    await update.message.reply_text(
        "🚀 أهلاً بك في بوت الستيكرات الاحترافي!\n\n"
        "1. اضغط 'إنشاء حزمة' أولاً.\n"
        "2. اختر نوع التحويل (صورة أو فيديو).\n"
        "3. أرسل ملفك وسيضاف للحزمة فوراً.",
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
        pack_id = f"st_{user_id}_{clean_name}_by_{bot_info.username}"
        user_data[user_id]["pack_name"] = pack_id
        user_data[user_id]["waiting_for_name"] = False
        await update.message.reply_text(f"✅ تم تفعيل الحزمة: {text}\nتستطيع الآن البدء بصنع الستيكرات.")

    elif text == "🗂️ حزمي الحالية":
        pack = user_data[user_id].get("pack_name")
        if pack:
            await update.message.reply_text(f"🔗 رابط حزمتك الحالية:\nt.me/addstickers/{pack}")
        else:
            await update.message.reply_text("⚠️ لم تنشئ حزمة بعد.")

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = user_data.get(user_id, {}).get("mode")
    
    if not mode:
        await update.message.reply_text("⚠️ اختر 'صورة' أو 'فيديو' من القائمة أولاً!")
        return

    file_prefix = f"temp_{user_id}"
    out_path = ""

    try:
        status_msg = await update.message.reply_text("⏳ جاري المعالجة...")
        
        # --- معالجة الصور ---
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            await file.download_to_drive(f"{file_prefix}.jpg")
            img = Image.open(f"{file_prefix}.jpg").convert("RGBA")
            img.thumbnail((512, 512), LANCZOS)
            out_path = f"{user_id}.webp"
            img.save(out_path, "WEBP")
            stk_type = "static"
        
        # --- معالجة الفيديوهات ---
        elif update.message.video or update.message.video_note:
            media = update.message.video or update.message.video_note
            file = await media.get_file()
            await file.download_to_drive(f"{file_prefix}.mp4")
            clip = VideoFileClip(f"{file_prefix}.mp4")
            
            # قص الفيديو ليكون متوافقاً مع تلغرام (أقل من 3 ثوانٍ)
            duration = min(2.9, clip.duration)
            try: clip = clip.subclip(0, duration)
            except: clip = clip.cropped(0, duration)
            
            # تغيير الحجم
            w, h = clip.size
            if w > h: clip = clip.resize(width=512)
            else: clip = clip.resize(height=512)
            
            out_path = f"{user_id}.webm"
            clip.write_videofile(out_path, codec="libvpx-vp9", fps=30, bitrate="400k", audio=False, logger=None, ffmpeg_params=["-pix_fmt", "yuva420p"])
            clip.close()
            stk_type = "video"

        # إرسال الستيكر المنفرد
        with open(out_path, "rb") as f:
            await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=f)

        # --- نظام إضافة الحزم الذكي ---
        pack_name = user_data[user_id].get("pack_name")
        if pack_name:
            with open(out_path, "rb") as f:
                # إنشاء كائن الستيكر مع التوافق لكل الإصدارات
                try:
                    sticker_obj = InputSticker(sticker=f, emoji_list=["✨"], format=stk_type)
                except:
                    sticker_obj = InputSticker(sticker=f, emoji_list=["✨"])

                try:
                    # محاولة الإضافة (للنسخ الحديثة)
                    await context.bot.add_sticker_to_set(user_id=user_id, name=pack_name, sticker=sticker_obj)
                except:
                    try:
                        # محاولة الإضافة (للنسخ الأقدم)
                        await context.bot.add_sticker_to_set(user_id=user_id, name=pack_name, stickers=[sticker_obj])
                    except:
                        # إنشاء حزمة جديدة إذا لم تكن موجودة
                        try:
                            await context.bot.create_new_sticker_set(
                                user_id=user_id, name=pack_name, title="Pro Pack", 
                                stickers=[sticker_obj], sticker_format=stk_type
                            )
                        except:
                            await context.bot.create_new_sticker_set(
                                user_id=user_id, name=pack_name, title="Pro Pack", 
                                stickers=[sticker_obj]
                            )
                await update.message.reply_text("✅ تمت الإضافة للحزمة!")

    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")
    finally:
        # تنظيف الملفات المؤقتة
        for temp_file in [f"{file_prefix}.jpg", f"{file_prefix}.mp4", out_path]:
            if os.path.exists(temp_file): os.remove(temp_file)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE, handle_media))
    app.run_polling()
    
