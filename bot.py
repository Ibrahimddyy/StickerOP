import os
import sqlite3
import logging
from PIL import Image

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# حل مشكلة ANTIALIAS الجذري
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = getattr(Image, 'LANCZOS', 1)

# حل مشكلة استيراد MoviePy (تجنب خطأ ModuleNotFoundError)
try:
    from moviepy.editor import VideoFileClip
except Exception:
    try:
        from moviepy.video.io.VideoFileClip import VideoFileClip
    except Exception as e:
        logger.error(f"MoviePy Import Error: {e}")

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

# --- قاعدة بيانات الحزم ---
def db_init():
    conn = sqlite3.connect("stickers_bot.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS packs (user_id INTEGER, pack_name TEXT, pack_title TEXT)")
    conn.commit()
    conn.close()

def add_pack_to_db(user_id, name, title):
    conn = sqlite3.connect("stickers_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO packs VALUES (?, ?, ?)", (user_id, name, title))
    conn.commit()
    conn.close()

def get_user_packs(user_id):
    conn = sqlite3.connect("stickers_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT pack_name, pack_title FROM packs WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

db_init()

def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 تحويل صورة"), KeyboardButton("🎥 تحويل فيديو / GIF")],
        [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("🗂️ حزمي الحالية")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 البوت جاهز! اختر ماذا تريد أن تفعل:", reply_markup=main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get("state")

    if text == "📸 تحويل صورة":
        context.user_data["state"] = "waiting_media"
        await update.message.reply_text("📥 أرسل الصورة الآن...")
    
    elif text == "🎥 تحويل فيديو / GIF":
        context.user_data["state"] = "waiting_media"
        await update.message.reply_text("📥 أرسل الفيديو أو الـ GIF...")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = "waiting_title"
        await update.message.reply_text("✍️ أرسل عنوان الحزمة:")

    elif state == "waiting_title":
        context.user_data["temp_title"] = text
        context.user_data["state"] = "waiting_name"
        await update.message.reply_text("🔗 أرسل اسم الرابط بالإنجليزي:")

    elif state == "waiting_name":
        clean_name = "".join(e for e in text if e.isalnum())
        context.user_data["temp_name"] = f"{clean_name}_{user_id}_by_bot"
        context.user_data["state"] = "waiting_first_sticker"
        await update.message.reply_text("✅ الآن أرسل (أول ملصق) لتفعيلها:")

    # الخطوة الجديدة: استقبال الإيموجي قبل المعالجة
    elif state == "waiting_emoji":
        context.user_data["emoji"] = text
        await process_and_ask_pack(update, context)

    elif text.startswith("➕ إضافة إلى: "):
        await finalize_addition(update, context, text)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("state")
    
    # تحميل الملف وحفظ مساره مؤقتاً
    media = update.message.photo or update.message.video or update.message.animation or update.message.video_note
    if not media: return

    status = await update.message.reply_text("📥 تم استلام الملف..")
    file = await (media[-1].get_file() if update.message.photo else media.get_file())
    
    ext = "jpg" if update.message.photo else "mp4"
    path = f"raw_{user_id}.{ext}"
    await file.download_to_drive(path)
    
    context.user_data["raw_file"] = path
    context.user_data["is_video"] = not update.message.photo
    
    if state == "waiting_first_sticker":
        # في حالة الإنشاء، نستخدم إيموجي افتراضي للسرعة
        context.user_data["emoji"] = "✨"
        await process_and_ask_pack(update, context)
    else:
        context.user_data["state"] = "waiting_emoji"
        await status.edit_text("😃 رائع! الآن أرسل الإيموجي (Emoji) الذي تريده لهذا الملصق:")

async def process_and_ask_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_path = context.user_data.get("raw_file")
    is_video = context.user_data.get("is_video")
    emoji = context.user_data.get("emoji", "✨")
    
    status = await update.message.reply_text("⏳ جاري المعالجة الاحترافية...")
    out_path = f"out_{user_id}_{os.urandom(2).hex()}" + (".webm" if is_video else ".webp")

    try:
        if not is_video:
            img = Image.open(raw_path).convert("RGBA")
            img.thumbnail((512, 512), Image.ANTIALIAS)
            img.save(out_path, "WEBP")
            s_type = "static"
        else:
            clip = VideoFileClip(raw_path)
            clip = clip.subclip(0, min(2.9, clip.duration))
            w, h = clip.size
            clip = clip.resize(width=512) if w > h else clip.resize(height=512)
            clip.write_videofile(out_path, codec="libvpx-vp9", fps=30, bitrate="400k", audio=False, logger=None)
            clip.close()
            s_type = "video"

        context.user_data["final_path"] = out_path
        context.user_data["final_type"] = s_type

        # إرسال المعاينة
        with open(out_path, "rb") as f:
            await context.bot.send_sticker(chat_id=user_id, sticker=f)

        if context.user_data.get("state") == "waiting_first_sticker":
            await create_pack(update, context)
        else:
            packs = get_user_packs(user_id)
            if not packs:
                await update.message.reply_text("⚠️ لا توجد حزم! اضغط 'إنشاء حزمة' أولاً.")
            else:
                buttons = [[KeyboardButton(f"➕ إضافة إلى: {p[1]}")] for p in packs]
                await update.message.reply_text("📥 اختر الحزمة المراد الإضافة إليها:", 
                                                reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        await status.delete()
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ تقني: {str(e)}")
    finally:
        if raw_path and os.path.exists(raw_path): os.remove(raw_path)

async def create_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = context.user_data["temp_name"]
    title = context.user_data["temp_title"]
    path = context.user_data["final_path"]
    s_type = context.user_data["final_type"]
    
    try:
        with open(path, "rb") as f:
            # تم حل مشكلة الـ format عبر استخدامه فقط في مكانه الصحيح
            stk = InputSticker(sticker=f, emoji_list=[context.user_data["emoji"]])
            await context.bot.create_new_sticker_set(
                user_id=user_id, name=name, title=title, 
                stickers=[stk], sticker_format=s_type
            )
        add_pack_to_db(user_id, name, title)
        await update.message.reply_text(f"🎉 تم إنشاء الحزمة!\nt.me/addstickers/{name}", reply_markup=main_menu())
        context.user_data.clear()
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في الإنشاء: {e}")

async def finalize_addition(update: Update, context: ContextTypes.DEFAULT_TYPE, text: Update):
    user_id = update.effective_user.id
    pack_title = text.replace("➕ إضافة إلى: ", "")
    packs = get_user_packs(user_id)
    real_name = next((p[0] for p in packs if p[1] == pack_title), None)
    
    path = context.user_data.get("final_path")
    if real_name and path:
        try:
            with open(path, "rb") as f:
                stk = InputSticker(sticker=f, emoji_list=[context.user_data["emoji"]])
                await context.bot.add_sticker_to_set(user_id=user_id, name=real_name, sticker=stk)
            await update.message.reply_text(f"✅ تمت الإضافة لـ {pack_title}!", reply_markup=main_menu())
            if os.path.exists(path): os.remove(path)
            context.user_data.clear()
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))
    app.run_polling(drop_pending_updates=True)
    
