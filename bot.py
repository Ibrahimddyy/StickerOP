import os
import sqlite3
import logging
from PIL import Image

# إعداد السجلات التشخيصية
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# حل مشكلة ANTIALIAS لضمان جودة الملصقات
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = getattr(Image, 'LANCZOS', 1)

try:
    from moviepy.editor import VideoFileClip
except ImportError:
    from moviepy.video.io.VideoFileClip import VideoFileClip

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

# --- لوحة التحكم ---
def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 تحويل صورة"), KeyboardButton("🎥 تحويل فيديو / GIF")],
        [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("🗂️ حزمي الحالية")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌟 أهلاً بك في النسخة المطورة!\n\n"
        "الآن يمكنك اختيار الإيموجي الخاص بكل ملصق وإضافته لأي حزمة تريد.",
        reply_markup=main_menu()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get("state")

    if text == "📸 تحويل صورة":
        context.user_data["mode"] = "photo"
        await update.message.reply_text("📥 أرسل الصورة الآن...")
    
    elif text == "🎥 تحويل فيديو / GIF":
        context.user_data["mode"] = "video"
        await update.message.reply_text("📥 أرسل الفيديو أو الـ GIF (أقل من 3 ثوانٍ)...")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = "waiting_title"
        await update.message.reply_text("✍️ أرسل (عنوان الحزمة) باللغة التي تحب:")

    elif state == "waiting_title":
        context.user_data["temp_title"] = text
        context.user_data["state"] = "waiting_name"
        await update.message.reply_text("🔗 أرسل (اسم الرابط) بالإنجليزي فقط:")

    elif state == "waiting_name":
        clean_name = "".join(e for e in text if e.isalnum())
        bot_info = await context.bot.get_me()
        full_name = f"{clean_name}_{user_id}_by_{bot_info.username}"
        context.user_data["temp_name"] = full_name
        context.user_data["state"] = "waiting_first_sticker"
        await update.message.reply_text("✅ رائع! الآن أرسل (أول ملصق) لتفعيل الحزمة:")

    elif text == "🗂️ حزمي الحالية":
        packs = get_user_packs(user_id)
        if not packs:
            await update.message.reply_text("⚠️ ليس لديك حزم حالياً.")
        else:
            msg = "📚 حزمك النشطة:\n\n"
            for p in packs:
                msg += f"🔹 {p[1]}: t.me/addstickers/{p[0]}\n"
            await update.message.reply_text(msg)

    # --- الميزة الجديدة: استقبال الإيموجي ---
    elif state == "waiting_for_emoji":
        # حفظ الإيموجي في الذاكرة المؤقتة
        context.user_data["temp_emoji"] = text
        packs = get_user_packs(user_id)
        if not packs:
            await update.message.reply_text("⚠️ ملصقك جاهز لكن لا توجد حزمة! أنشئ حزمة أولاً.")
            context.user_data["state"] = None
        else:
            context.user_data["state"] = "selecting_pack"
            buttons = [[KeyboardButton(f"➕ إضافة إلى: {p[1]}")] for p in packs]
            await update.message.reply_text(f"👍 تم حفظ الإيموجي: {text}\n\nالآن اختر الحزمة:", 
                                            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))

    # --- الإضافة النهائية للحزمة ---
    elif text.startswith("➕ إضافة إلى: "):
        pack_title = text.replace("➕ إضافة إلى: ", "")
        packs = get_user_packs(user_id)
        real_name = next((p[0] for p in packs if p[1] == pack_title), None)
        
        if real_name and "last_sticker" in context.user_data:
            path, s_type = context.user_data["last_sticker"]
            emoji = context.user_data.get("temp_emoji", "✨") # إيموجي افتراضي إذا لم يرسل المستخدم
            
            try:
                with open(path, "rb") as f:
                    stk = InputSticker(sticker=f, emoji_list=[emoji], format=s_type)
                    await context.bot.add_sticker_to_set(user_id=user_id, name=real_name, sticker=stk)
                await update.message.reply_text(f"✅ تمت الإضافة بنجاح باستخدام إيموجي {emoji}!", reply_markup=main_menu())
                if os.path.exists(path): os.remove(path)
                context.user_data.clear() # تصفير الذاكرة المؤقتة بعد النجاح
            except Exception as e:
                await update.message.reply_text(f"❌ خطأ: {str(e)}")

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("state")
    
    media = update.message.photo or update.message.video or update.message.animation or update.message.video_note
    if not media: return

    try:
        status_msg = await update.message.reply_text("⏳ جاري المعالجة...")
        file_path = f"file_{user_id}"
        out_path = ""

        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            await file.download_to_drive(f"{file_path}.jpg")
            img = Image.open(f"{file_path}.jpg").convert("RGBA")
            img.thumbnail((512, 512), Image.ANTIALIAS)
            out_path = f"{user_id}_{os.urandom(2).hex()}.webp"
            img.save(out_path, "WEBP")
            s_type = "static"
        
        else: # فيديو أو GIF
            v_file = update.message.video or update.message.animation or update.message.video_note
            file = await v_file.get_file()
            await file.download_to_drive(f"{file_path}.mp4")
            clip = VideoFileClip(f"{file_path}.mp4")
            duration = min(2.9, clip.duration)
            clip = clip.subclip(0, duration)
            w, h = clip.size
            clip = clip.resize(width=512) if w > h else clip.resize(height=512)
            out_path = f"{user_id}_{os.urandom(2).hex()}.webm"
            clip.write_videofile(out_path, codec="libvpx-vp9", fps=30, bitrate="400k", audio=False, logger=None)
            clip.close()
            s_type = "video"

        # إذا كنا ننشئ حزمة جديدة
        if state == "waiting_first_sticker":
            title = context.user_data["temp_title"]
            name = context.user_data["temp_name"]
            with open(out_path, "rb") as f:
                stk = InputSticker(sticker=f, emoji_list=["✨"], format=s_type)
                await context.bot.create_new_sticker_set(user_id=user_id, name=name, title=title, stickers=[stk], sticker_format=s_type)
            add_pack_to_db(user_id, name, title)
            await update.message.reply_text(f"🎉 تم إنشاء الحزمة بنجاح!\nرابطها: t.me/addstickers/{name}")
            context.user_data.clear()
            if os.path.exists(out_path): os.remove(out_path)
        else:
            # إرسال الملصق للمعاينة وطلب الإيموجي
            with open(out_path, "rb") as f:
                await context.bot.send_sticker(chat_id=user_id, sticker=f)
            
            context.user_data["last_sticker"] = (out_path, s_type)
            context.user_data["state"] = "waiting_for_emoji"
            await update.message.reply_text("😄 ملصقك جاهز! الآن أرسل الإيموجي (Emoji) الذي تريده لهذا الملصق:")

        await status_msg.delete()

    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))
    app.run_polling(drop_pending_updates=True)
    
