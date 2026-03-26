import os, logging, asyncio, uuid
from PIL import Image
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import StickerFormat

# إعداد السجلات الأساسية لضمان الاستقرار
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# حل مشكلة MoviePy البديل
try:
    from moviepy.editor import VideoFileClip
except:
    try: from moviepy import VideoFileClip
    except: from moviepy.video.io.VideoFileClip import VideoFileClip

TOKEN = os.getenv("BOT_TOKEN")

# --- تم حذف قاعدة البيانات تماماً لضمان عدم توقف البوت ---

# واجهة الأزرار الرائعة
def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 تحويل صورة"), KeyboardButton("🎥 تحويل فيديو / GIF")],
        [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("🗂️ حزمي الحالية")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # تنظيف شامل لذاكرة الجلسة القديمة
    if user_id in context.user_data: context.user_data.clear()
    
    await update.message.reply_text(
        "🚀 أهلاً بك! هذا البوت يعمل الآن بنظام الذاكرة المؤقتة فائق الاستقرار.\n"
        "لن يتوقف عند الإيموجي مجدداً.\n"
        "أرسل صورتك أو فيديوك للبدء:", 
        reply_markup=main_menu()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get("state")

    # التعامل مع القائمة الرئيسية
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
        # بما أنه لا توجد قاعدة بيانات، سنبحث في الحزم التي أنشأها البوت في هذه الجلسة
        packs = context.user_data.get("my_packs_this_session", [])
        if not packs:
            await update.message.reply_text("⚠️ لا توجد حزم نشطة في هذه الجلسة.")
        else:
            msg = "📚 حزمك النشطة حالياً:\n\n" + "\n".join([f"🔹 {p}" for p in packs])
            await update.message.reply_text(msg)

    # التعامل مع حالات إنشاء الحزمة
    elif state == "waiting_title":
        context.user_data.update({"temp_title": text, "state": "waiting_name"})
        await update.message.reply_text("🔗 أرسل اسم الرابط بالإنجليزي (مثال: MyPack):")

    elif state == "waiting_name":
        clean_name = "".join(e for e in text if e.isalnum())
        context.user_data.update({"temp_name": clean_name, "state": "waiting_first_sticker"})
        await update.message.reply_text("✅ أرسل الآن الملصق الأول لتفعيلها:")

    # حل مشكلة "التوقف عند الإيموجي": معالجة في الذاكرة فقط
    elif state == "waiting_emoji":
        if "last_sticker_info" in context.user_data:
            # حفظ الإيموجي في الذاكرة المؤقتة
            context.user_data["last_sticker_info"]["emoji"] = text
            
            # البحث عن حزم تم إنشاؤها في هذه الجلسة
            packs = context.user_data.get("my_packs_this_session", [])
            if not packs:
                await update.message.reply_text("💡 ملصقك جاهز! لكن لا توجد حزمة نشطة. اضغط 'إنشاء حزمة' لحفظه.")
                # تنظيف الملف لعدم تراكمه
                path = context.user_data["last_sticker_info"].get("path")
                if path and os.path.exists(path): os.remove(path)
                context.user_data.clear()
            else:
                context.user_data["state"] = "selecting_pack"
                btns = [[KeyboardButton(f"➕ إضافة إلى: {p}")] for p in packs]
                await update.message.reply_text(f"👍 تم اختيار {text}. اختر الحزمة:", reply_markup=ReplyKeyboardMarkup(btns, resize_keyboard=True))

    elif text.startswith("➕ إضافة إلى: "):
        await add_to_existing_pack_action(update, context, text)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message
    media = msg.photo or msg.video or msg.animation or msg.video_note
    if not media: return

    try:
        status = await update.message.reply_text("⏳ جاري المعالجة...")
        file = await (media[-1].get_file() if msg.photo else media.get_file())
        raw_path = f"raw_{user_id}_{uuid.uuid4().hex[:4]}.mp4"
        await file.download_to_drive(raw_path)
        
        # المعالجة الأساسية التي حلت مشكلة الفيديو
        out_path, s_type = await process_media_core(raw_path, user_id, not msg.photo)
        
        # حفظ المعلومات في الذاكرة المؤقتة لتجنب انهيار قاعدة البيانات
        context.user_data["last_sticker_info"] = {"path": out_path, "type": s_type, "emoji": "✨"}
        
        if context.user_data.get("state") == "waiting_first_sticker":
            await create_pack_action(update, context)
        else:
            context.user_data["state"] = "waiting_emoji"
            with open(out_path, "rb") as f: await context.bot.send_sticker(user_id, f)
            await update.message.reply_text("😄 ملصقك جاهز! أرسل (الإيموجي) المخصص له:")
        
        await status.delete()
        if os.path.exists(raw_path): os.remove(raw_path)
    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ خطأ: {e}")

async def process_media_core(raw_path, user_id, is_video):
    out = f"out_{user_id}_{uuid.uuid4().hex[:4]}" + (".webm" if is_video else ".webp")
    if not is_video:
        img = Image.open(raw_path).convert("RGBA")
        # حل مشكلة ANTIALIAS للأبد
        img.thumbnail((512, 512), Image.LANCZOS)
        img.save(out, "WEBP")
        return out, StickerFormat.STATIC
    else:
        # إعدادات الفيديو فائقة التوافق (GIFs)
        clip = VideoFileClip(raw_path).subclip(0, 2.5)
        clip = clip.resize(width=512) if clip.w > clip.h else clip.resize(height=512)
        clip.write_videofile(out, codec="libvpx-vp9", fps=30, bitrate="180k", audio=False, logger=None, ffmpeg_params=['-pix_fmt', 'yuva420p'])
        clip.close()
        return out, StickerFormat.VIDEO

async def create_pack_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    info = context.user_data.get("last_sticker_info")
    bot = await context.bot.get_me()
    
    # بناء الاسم تلقائياً لضمان النجاح
    clean_name = context.user_data["temp_name"]
    unique_suffix = uuid.uuid4().hex[:4]
    full_name = f"st_{clean_name}_{unique_suffix}_{user_id}_by_{bot.username}"
    title = context.user_data["temp_title"]
    
    try:
        with open(info["path"], "rb") as f:
            stk = InputSticker(f, [info["emoji"]])
            await context.bot.create_new_sticker_set(
                user_id=user_id, name=full_name, title=title, 
                stickers=[stk], sticker_format=info["type"]
            )
        
        # حفظ الحزمة في ذاكرة الجلسة فقط (ليس قاعدة البيانات)
        if "my_packs_this_session" not in context.user_data:
            context.user_data["my_packs_this_session"] = []
        context.user_data["my_packs_this_session"].append(full_name)
        
        await update.message.reply_text(f"🎉 تم إنشاء الحزمة بنجاح!\nالرابط: t.me/addstickers/{full_name}", reply_markup=main_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ فشل من تليجرام: {str(e)}")
    finally:
        if os.path.exists(info["path"]): os.remove(info["path"])
        # تنظيف جزئي لذاكرة المستخدم للحفاظ على المسار الصحيح
        context.user_data.pop("last_sticker_info", None)
        context.user_data.pop("state", None)
        context.user_data.pop("mode", None)

async def add_to_existing_pack_action(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    user_id = update.effective_user.id
    info = context.user_data.get("last_sticker_info")
    
    pack_name = text.replace("➕ إضافة إلى: ", "")
    
    if pack_name and info:
        try:
            with open(info["path"], "rb") as f:
                # إضافة الملصق بالإيموجي المحدد
                await context.bot.add_sticker_to_set(user_id=user_id, name=pack_name, sticker=InputSticker(f, [info["emoji"]]))
            await update.message.reply_text(f"✅ تمت إضافة الملصق بنجاح!", reply_markup=main_menu())
        except Exception as e:
            await update.message.reply_text(f"❌ فشل الإضافة: {str(e)}")
        finally:
            if os.path.exists(info["path"]): os.remove(info["path"])
            context.user_data.clear()

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))
    app.run_polling(drop_pending_updates=True)
    
