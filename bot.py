import os
import sqlite3
import logging
import asyncio
import uuid
from PIL import Image

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = getattr(Image, 'LANCZOS', 1)

try:
    from moviepy.editor import VideoFileClip
except ImportError:
    try: from moviepy import VideoFileClip
    except ImportError: from moviepy.video.io.VideoFileClip import VideoFileClip

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import StickerFormat

TOKEN = os.getenv("BOT_TOKEN")

# --- إدارة قاعدة البيانات ---
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
    user_id = update.effective_user.id
    if user_id in context.user_data: context.user_data.clear()
    await update.message.reply_text("👋 أهلاً بك! اختر نوع الملصق للبدء:", reply_markup=main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get("state")

    if text == "📸 تحويل صورة":
        context.user_data["mode"] = "photo"
        context.user_data["state"] = "waiting_media"
        await update.message.reply_text("📥 أرسل الصورة الآن...")
    
    elif text == "🎥 تحويل فيديو / GIF":
        context.user_data["mode"] = "video"
        context.user_data["state"] = "waiting_media"
        await update.message.reply_text("📥 أرسل الفيديو أو الـ GIF (أقل من 3 ثوانٍ)...")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = "waiting_title"
        await update.message.reply_text("✍️ أرسل عنوان الحزمة بالعربي:")

    elif state == "waiting_title":
        context.user_data["temp_title"] = text
        context.user_data["state"] = "waiting_name"
        await update.message.reply_text("🔗 أرسل اسم الرابط بالإنجليزي (مثلاً: MyPack2026):")

    elif state == "waiting_name":
        # تنظيف الاسم
        clean_name = "".join(e for e in text if e.isalnum())
        context.user_data["temp_name"] = clean_name
        context.user_data["state"] = "waiting_first_sticker"
        await update.message.reply_text("✅ الآن أرسل (أول ملصق) لتفعيل هذه الحزمة:")

    elif state == "waiting_emoji":
        if "last_sticker_info" in context.user_data:
            context.user_data["last_sticker_info"]["emoji"] = text
            packs = get_user_packs(user_id)
            if not packs:
                await update.message.reply_text("⚠️ لا تملك حزم! اضغط 'إنشاء حزمة جديدة' أولاً.")
                context.user_data.clear()
            else:
                context.user_data["state"] = "selecting_pack"
                buttons = [[KeyboardButton(f"➕ إضافة إلى: {p[1]}")] for p in packs]
                await update.message.reply_text(f"👍 تم اختيار {text}. الآن اختر الحزمة:", 
                                                reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))

    elif text.startswith("➕ إضافة إلى: "):
        await add_to_existing_pack_action(update, context, text)

    elif text == "🗂️ حزمي الحالية":
        packs = get_user_packs(user_id)
        if not packs:
            await update.message.reply_text("⚠️ لا تملك حزم مسجلة في البوت حالياً.")
        else:
            msg = "📚 حزمك النشطة:\n\n"
            for p in packs:
                msg += f"🔹 {p[1]}: t.me/addstickers/{p[0]}\n"
            await update.message.reply_text(msg)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("state")
    msg = update.message
    media = msg.photo or msg.video or msg.animation or msg.video_note
    if not media: return

    try:
        status_msg = await update.message.reply_text("⏳ جاري المعالجة...")
        file = await (media[-1].get_file() if msg.photo else media.get_file())
        ext = "jpg" if msg.photo else "mp4"
        raw_path = f"raw_{user_id}_{uuid.uuid4().hex[:6]}.{ext}"
        await file.download_to_drive(raw_path)
        
        out_path, s_type = await process_media_core(raw_path, user_id, not msg.photo)
        
        if state == "waiting_first_sticker":
            context.user_data["last_sticker_info"] = {"path": out_path, "type": s_type, "emoji": "✨"}
            await create_pack_action(update, context)
        else:
            context.user_data["last_sticker_info"] = {"path": out_path, "type": s_type, "emoji": None}
            context.user_data["state"] = "waiting_emoji"
            with open(out_path, "rb") as f:
                await context.bot.send_sticker(chat_id=user_id, sticker=f)
            await update.message.reply_text("😄 ملصقك جاهز! الآن أرسل (الإيموجي) المخصص له:")

        await status_msg.delete()
        if os.path.exists(raw_path): os.remove(raw_path)

    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

async def process_media_core(raw_path, user_id, is_video):
    out_path = f"out_{user_id}_{uuid.uuid4().hex[:6]}" + (".webm" if is_video else ".webp")
    if not is_video:
        img = Image.open(raw_path).convert("RGBA")
        img.thumbnail((512, 512), Image.ANTIALIAS)
        img.save(out_path, "WEBP")
        return out_path, StickerFormat.STATIC
    else:
        clip = VideoFileClip(raw_path)
        clip = clip.subclip(0, min(2.8, clip.duration))
        if clip.size[0] > clip.size[1]: clip = clip.resize(width=512)
        else: clip = clip.resize(height=512)
        # إعدادات لضمان القبول في الحزم
        clip.write_videofile(out_path, codec="libvpx-vp9", fps=30, bitrate="200k", audio=False, logger=None, ffmpeg_params=['-pix_fmt', 'yuva420p', '-metadata:s:v:0', 'alpha_mode=1'])
        clip.close()
        return out_path, StickerFormat.VIDEO

async def create_pack_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sticker_info = context.user_data.get("last_sticker_info")
    bot_info = await context.bot.get_me()
    
    # إضافة معرف فريد للرابط لضمان عدم التكرار
    clean_name = context.user_data["temp_name"]
    unique_suffix = uuid.uuid4().hex[:4]
    full_name = f"st_{clean_name}_{unique_suffix}_{user_id}_by_{bot_info.username}"
    title = context.user_data["temp_title"]

    try:
        with open(sticker_info["path"], "rb") as f:
            stk = InputSticker(sticker=f, emoji_list=[sticker_info["emoji"]])
            await context.bot.create_new_sticker_set(
                user_id=user_id, name=full_name, title=title, 
                stickers=[stk], sticker_format=sticker_info["type"]
            )
        add_pack_to_db(user_id, full_name, title, sticker_info["type"].value)
        await update.message.reply_text(f"🎉 تم إنشاء الحزمة بنجاح!\nالرابط: t.me/addstickers/{full_name}", reply_markup=main_menu())
    except Exception as e:
        # الكشف عن الخطأ الحقيقي من تليجرام
        await update.message.reply_text(f"❌ فشل من تليجرام: {str(e)}\nنصيحة: جرب اسماً أطول للرابط.")
    finally:
        if sticker_info and os.path.exists(sticker_info["path"]): os.remove(sticker_info["path"])
        context.user_data.clear()

async def add_to_existing_pack_action(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    user_id = update.effective_user.id
    sticker_info = context.user_data.get("last_sticker_info")
    pack_title = text.replace("➕ إضافة إلى: ", "")
    packs = get_user_packs(user_id)
    real_name = next((p[0] for p in packs if p[1] == pack_title), None)
    
    if real_name and sticker_info:
        try:
            with open(sticker_info["path"], "rb") as f:
                stk = InputSticker(sticker=f, emoji_list=[sticker_info["emoji"]])
                await context.bot.add_sticker_to_set(user_id=user_id, name=real_name, sticker=stk)
            await update.message.reply_text(f"✅ تمت الإضافة بنجاح!", reply_markup=main_menu())
        except Exception as e:
            await update.message.reply_text(f"❌ فشل الإضافة: {str(e)}")
        finally:
            if os.path.exists(sticker_info["path"]): os.remove(sticker_info["path"])
            context.user_data.clear()

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))
    app.run_polling(drop_pending_updates=True)
        
