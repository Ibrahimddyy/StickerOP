import os
import sqlite3
import logging
import asyncio
from PIL import Image

# إعداد السجلات لمراقبة أداء البوت في Railway
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# حل مشكلة Pillow الحديثة لضمان جودة الملصقات
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

# --- إدارة قاعدة البيانات (حفظ الحزم) ---
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

# --- واجهة المستخدم (الأزرار) ---
def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 تحويل صورة"), KeyboardButton("🎥 تحويل فيديو / GIF")],
        [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("🗂️ حزمي الحالية")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 أهلاً بك في بوت الملصقات الاحترافي!\n\n"
        "1️⃣ اختر نوع التحويل من الأزرار.\n"
        "2️⃣ أرسل الملف (صورة، فيديو، GIF).\n"
        "3️⃣ أرسل الإيموجي الذي تريده.\n"
        "4️⃣ اختر الحزمة التي تريد الإضافة إليها.",
        reply_markup=main_menu()
    )

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
        await update.message.reply_text("✍️ أرسل (عنوان الحزمة) كما سيظهر للناس:")

    elif state == "waiting_title":
        context.user_data["temp_title"] = text
        context.user_data["state"] = "waiting_name"
        await update.message.reply_text("🔗 أرسل (اسم الرابط) بالإنجليزي فقط (مثلاً: MyPack):")

    elif state == "waiting_name":
        context.user_data["temp_name"] = "".join(e for e in text if e.isalnum())
        context.user_data["state"] = "waiting_first_sticker"
        await update.message.reply_text("✅ الآن أرسل (أول ملصق) لتفعيل الحزمة الجديدة:")

    elif state == "waiting_emoji":
        # المستخدم أرسل الإيموجي، الآن نبدأ المعالجة الفعلية
        context.user_data["emoji"] = text
        await process_and_finalize(update, context)

    elif text.startswith("➕ إضافة إلى: "):
        await add_to_existing_pack(update, context, text)

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

    # تنزيل الملف وحفظه مؤقتاً
    file = await (media[-1].get_file() if msg.photo else media.get_file())
    ext = "jpg" if msg.photo else "mp4"
    raw_path = f"raw_{user_id}.{ext}"
    await file.download_to_drive(raw_path)
    
    context.user_data["raw_file"] = raw_path
    context.user_data["is_video"] = not msg.photo
    
    # الطلب من المستخدم إرسال الإيموجي قبل المعالجة
    if context.user_data.get("state") != "waiting_first_sticker":
        context.user_data["state"] = "waiting_emoji"
        await update.message.reply_text("😃 ملفك جاهز! الآن أرسل (الإيموجي) الذي تريده لهذا الملصق:")
    else:
        # في حالة أول ملصق بالحزمة، نستخدم إيموجي افتراضي
        context.user_data["emoji"] = "✨"
        await process_and_finalize(update, context)

async def process_and_finalize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_path = context.user_data.get("raw_file")
    is_video = context.user_data.get("is_video")
    emoji = context.user_data.get("emoji", "✨")
    
    status = await update.message.reply_text("⏳ جاري المعالجة الاحترافية للفيديو/الصورة...")
    out_path = f"out_{user_id}_{os.urandom(2).hex()}" + (".webm" if is_video else ".webp")

    try:
        if not is_video:
            img = Image.open(raw_path).convert("RGBA")
            img.thumbnail((512, 512), Image.ANTIALIAS)
            img.save(out_path, "WEBP")
            s_type = StickerFormat.STATIC
        else:
            # معالجة الفيديو لضمان عدم ظهوره "مخفياً"
            clip = VideoFileClip(raw_path)
            clip = clip.subclip(0, min(2.9, clip.duration))
            w, h = clip.size
            if w > h: clip = clip.resize(width=512)
            else: clip = clip.resize(height=512)
            
            # إعدادات الـ WEBM المتوافقة تماماً مع تليجرام
            clip.write_videofile(out_path, codec="libvpx-vp9", fps=30, bitrate="300k", audio=False, logger=None, ffmpeg_params=['-pix_fmt', 'yuva420p'])
            clip.close()
            s_type = StickerFormat.VIDEO

        context.user_data["final_path"] = out_path
        context.user_data["final_type"] = s_type

        # إرسال الملصق للمعاينة
        with open(out_path, "rb") as f:
            await context.bot.send_sticker(chat_id=user_id, sticker=f)

        # هل نحن في وضع إنشاء حزمة؟
        if context.user_data.get("state") == "waiting_first_sticker":
            await create_pack_action(update, context)
        else:
            packs = get_user_packs(user_id)
            if not packs:
                await update.message.reply_text("⚠️ ملصقك جاهز! لكن لا تملك حزم، اضغط 'إنشاء حزمة' لحفظه.")
            else:
                # عرض الحزم المتاحة للاختيار
                buttons = [[KeyboardButton(f"➕ إضافة إلى: {p[1]}")] for p in packs]
                await update.message.reply_text("📥 اختر الحزمة التي تريد الإضافة إليها:", 
                                                reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        await status.delete()

    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ خطأ تقني: {e}")
    finally:
        if raw_path and os.path.exists(raw_path): os.remove(raw_path)

async def create_pack_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_info = await context.bot.get_me()
    
    # بناء الاسم الصحيح للرابط
    clean_name = context.user_data["temp_name"]
    full_name = f"st_{clean_name}_{user_id}_by_{bot_info.username}"
    
    title = context.user_data["temp_title"]
    path = context.user_data["final_path"]
    s_type = context.user_data["final_type"]
    emoji = context.user_data["emoji"]

    try:
        with open(path, "rb") as f:
            # ربط الإيموجي بالملصق بشكل حقيقي
            stk = InputSticker(sticker=f, emoji_list=[emoji])
            await context.bot.create_new_sticker_set(
                user_id=user_id, name=full_name, title=title, 
                stickers=[stk], sticker_format=s_type
            )
        add_pack_to_db(user_id, full_name, title, s_type.value)
        await update.message.reply_text(f"🎉 تم إنشاء الحزمة بنجاح!\nالرابط: t.me/addstickers/{full_name}", reply_markup=main_menu())
        context.user_data.clear()
    except Exception as e:
        await update.message.reply_text(f"❌ فشل إنشاء الحزمة: {e}")

async def add_to_existing_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    user_id = update.effective_user.id
    pack_title = text.replace("➕ إضافة إلى: ", "")
    packs = get_user_packs(user_id)
    real_name = next((p[0] for p in packs if p[1] == pack_title), None)
    
    path = context.user_data.get("final_path")
    emoji = context.user_data.get("emoji", "✨")

    if real_name and path:
        try:
            with open(path, "rb") as f:
                stk = InputSticker(sticker=f, emoji_list=[emoji])
                await context.bot.add_sticker_to_set(user_id=user_id, name=real_name, sticker=stk)
            await update.message.reply_text(f"✅ تمت إضافة الملصق بنجاح بـ {emoji}!", reply_markup=main_menu())
            if os.path.exists(path): os.remove(path)
            context.user_data.clear()
        except Exception as e:
            await update.message.reply_text(f"❌ فشل الإضافة: {e}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))
    app.run_polling(drop_pending_updates=True)
        
