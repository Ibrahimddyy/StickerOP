import os
import sqlite3
import logging
import asyncio
from PIL import Image

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# حل مشكلة PIL الجديدة
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = getattr(Image, 'LANCZOS', 1)

try:
    from moviepy.editor import VideoFileClip
except ImportError:
    from moviepy.video.io.VideoFileClip import VideoFileClip

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import StickerFormat

TOKEN = os.getenv("BOT_TOKEN")

# --- قاعدة البيانات ---
def db_init():
    conn = sqlite3.connect("stickers_bot.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS packs (user_id INTEGER, pack_name TEXT, pack_title TEXT, type TEXT)")
    conn.commit()
    conn.close()

def add_pack_to_db(user_id, name, title, s_type):
    conn = sqlite3.connect("stickers_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO packs VALUES (?, ?, ?, ?)", (user_id, name, title, s_type))
    conn.commit()
    conn.close()

def get_user_packs(user_id):
    conn = sqlite3.connect("stickers_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT pack_name, pack_title, type FROM packs WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

db_init()

# --- القوائم ---
def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 تحويل صورة"), KeyboardButton("🎥 تحويل فيديو / GIF")],
        [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("🗂️ حزمي الحالية")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلاً بك! البوت الآن جاهز لإنشاء ملصقاتك.", reply_markup=main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get("state")

    if text == "📸 تحويل صورة":
        context.user_data["state"] = "waiting_media"
        context.user_data["is_video"] = False
        await update.message.reply_text("📥 أرسل الصورة الآن...")
    
    elif text == "🎥 تحويل فيديو / GIF":
        context.user_data["state"] = "waiting_media"
        context.user_data["is_video"] = True
        await update.message.reply_text("📥 أرسل الفيديو أو الـ GIF (أقل من 3 ثوانٍ)...")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = "waiting_title"
        await update.message.reply_text("✍️ أرسل (عنوان الحزمة) بالعربي أو الإنجليزي:")

    elif state == "waiting_title":
        context.user_data["temp_title"] = text
        context.user_data["state"] = "waiting_name"
        await update.message.reply_text("🔗 أرسل (اسم الرابط) بالإنجليزي فقط وبدون مسافات:")

    elif state == "waiting_name":
        clean_name = "".join(e for e in text if e.isalnum())
        context.user_data["temp_name"] = f"{clean_name}_{user_id}_by_bot"
        context.user_data["state"] = "waiting_first_sticker"
        await update.message.reply_text("✅ رائع! الآن أرسل (أول ملصق) لتفعيل الحزمة:")

    elif state == "waiting_emoji":
        # تخزين الإيموجي وبدء المعالجة
        context.user_data["emoji"] = text
        await process_media_logic(update, context)

    elif text.startswith("➕ إضافة إلى: "):
        await finalize_add_to_pack(update, context, text)

    elif text == "🗂️ حزمي الحالية":
        packs = get_user_packs(user_id)
        if not packs:
            await update.message.reply_text("⚠️ لا تملك حزم حالياً.")
        else:
            msg = "📚 حزمك النشطة:\n\n"
            for p in packs:
                msg += f"🔹 {p[1]}: t.me/addstickers/{p[0]}\n"
            await update.message.reply_text(msg)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message
    media = msg.photo or msg.video or msg.animation or msg.video_note
    if not media: return

    # تنزيل الملف وحفظه
    file = await (media[-1].get_file() if msg.photo else media.get_file())
    ext = "jpg" if msg.photo else "mp4"
    raw_path = f"raw_{user_id}.{ext}"
    await file.download_to_drive(raw_path)
    
    context.user_data["raw_file"] = raw_path
    context.user_data["is_video"] = not msg.photo
    context.user_data["state"] = "waiting_emoji"
    
    await update.message.reply_text("😃 وصل الملف! الآن أرسل الإيموجي (Emoji) الذي تريده لهذا الملصق:")

async def process_media_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_path = context.user_data.get("raw_file")
    is_video = context.user_data.get("is_video")
    emoji = context.user_data.get("emoji", "✨")
    
    progress = await update.message.reply_text("⏳ جاري تحضير الملصق بجودة عالية...")
    out_path = f"out_{user_id}_{os.urandom(2).hex()}" + (".webm" if is_video else ".webp")

    try:
        if not is_video:
            # معالجة الصور
            img = Image.open(raw_path).convert("RGBA")
            img.thumbnail((512, 512), Image.ANTIALIAS)
            img.save(out_path, "WEBP")
            s_type = StickerFormat.STATIC
        else:
            # معالجة الفيديوهات لضمان عدم ظهورها مخفية
            clip = VideoFileClip(raw_path)
            duration = min(2.9, clip.duration)
            clip = clip.subclip(0, duration)
            w, h = clip.size
            if w > h:
                clip = clip.resize(width=512)
            else:
                clip = clip.resize(height=512)
            
            # إعدادات الـ WEBM الصارمة لتليجرام
            clip.write_videofile(out_path, codec="libvpx-vp9", fps=30, bitrate="300k", audio=False, logger=None)
            clip.close()
            s_type = StickerFormat.VIDEO

        context.user_data["final_path"] = out_path
        context.user_data["final_type"] = s_type

        # إرسال معاينة
        with open(out_path, "rb") as f:
            await context.bot.send_sticker(chat_id=user_id, sticker=f)

        # هل نحن في طور إنشاء حزمة أم إضافة؟
        if context.user_data.get("state") == "waiting_first_sticker" or "temp_name" in context.user_data:
            await create_new_pack_logic(update, context)
        else:
            packs = get_user_packs(user_id)
            if not packs:
                await update.message.reply_text("⚠️ ملصقك جاهز، لكن لا توجد حزمة! اضغط 'إنشاء حزمة جديدة' أولاً.")
            else:
                buttons = [[KeyboardButton(f"➕ إضافة إلى: {p[1]}")] for p in packs]
                await update.message.reply_text("📥 اختر الحزمة التي تريد إضافة هذا الملصق إليها:", 
                                                reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        await progress.delete()

    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ خطأ في المعالجة: {e}")
    finally:
        if raw_path and os.path.exists(raw_path): os.remove(raw_path)

async def create_new_pack_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = context.user_data["temp_name"]
    title = context.user_data["temp_title"]
    path = context.user_data["final_path"]
    s_type = context.user_data["final_type"]
    emoji = context.user_data["emoji"]

    try:
        with open(path, "rb") as f:
            # الحل الجذري لخطأ الـ Format
            stk = InputSticker(sticker=f, emoji_list=[emoji])
            await context.bot.create_new_sticker_set(
                user_id=user_id, name=name, title=title, 
                stickers=[stk], sticker_format=s_type
            )
        add_pack_to_db(user_id, name, title, s_type.value)
        await update.message.reply_text(f"🎉 تم إنشاء الحزمة بنجاح!\nرابطها: t.me/addstickers/{name}", reply_markup=main_menu())
        context.user_data.clear() # مسح الذاكرة المؤقتة بعد النجاح
    except Exception as e:
        await update.message.reply_text(f"❌ فشل إنشاء الحزمة: {e}")

async def finalize_add_to_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
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
            await update.message.reply_text(f"✅ تمت إضافة الملصق بنجاح!", reply_markup=main_menu())
            if os.path.exists(path): os.remove(path)
            context.user_data.clear()
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ أثناء الإضافة: {e}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))
    app.run_polling(drop_pending_updates=True)
    
