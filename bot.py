import os, sqlite3, logging, asyncio, uuid
from PIL import Image
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import StickerFormat

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from moviepy.editor import VideoFileClip
except:
    from moviepy.video.io.VideoFileClip import VideoFileClip

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

# --- الواجهة ---
def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 تحويل صورة"), KeyboardButton("🎥 تحويل فيديو / GIF")],
        [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("🗂️ حزمي الحالية")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🚀 أهلاً بك! لننهي موضوع الحزمة الآن. اختر النوع:", reply_markup=main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get("state")

    if text == "📸 تحويل صورة":
        context.user_data.update({"mode": "photo", "state": "waiting_media"})
        await update.message.reply_text("📥 أرسل الصورة...")
    
    elif text == "🎥 تحويل فيديو / GIF":
        context.user_data.update({"mode": "video", "state": "waiting_media"})
        await update.message.reply_text("📥 أرسل الفيديو (أقل من 3 ثوانٍ)...")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = "waiting_title"
        await update.message.reply_text("✍️ أرسل عنوان الحزمة بالعربي:")

    elif state == "waiting_title":
        context.user_data.update({"temp_title": text, "state": "waiting_name"})
        await update.message.reply_text("🔗 أرسل اسم الرابط بالإنجليزي (مثلاً: MyBestPack):")

    elif state == "waiting_name":
        clean_name = "".join(e for e in text if e.isalnum())
        context.user_data.update({"temp_name": clean_name, "state": "waiting_first_sticker"})
        await update.message.reply_text("✅ أرسل الآن الملصق الأول لتفعيل الحزمة:")

    elif state == "waiting_emoji":
        if "last_sticker_info" in context.user_data:
            context.user_data["last_sticker_info"]["emoji"] = text
            packs = get_user_packs(user_id)
            if packs:
                context.user_data["state"] = "selecting_pack"
                btns = [[KeyboardButton(f"➕ إضافة إلى: {p[1]}")] for p in packs]
                await update.message.reply_text(f"👍 اختر الحزمة للإضافة:", reply_markup=ReplyKeyboardMarkup(btns, resize_keyboard=True))

    elif text.startswith("➕ إضافة إلى: "):
        await add_to_existing_pack_action(update, context, text)

    elif text == "🗂️ حزمي الحالية":
        packs = get_user_packs(user_id)
        msg = "📚 حزمك:\n\n" + "\n".join([f"🔹 {p[1]}: t.me/addstickers/{p[0]}" for p in packs]) if packs else "⚠️ لا توجد حزم."
        await update.message.reply_text(msg)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message
    media = msg.photo or msg.video or msg.animation or msg.video_note
    if not media: return

    try:
        status = await update.message.reply_text("⏳ جاري المعالجة القصوى...")
        file = await (media[-1].get_file() if msg.photo else media.get_file())
        raw_path = f"raw_{user_id}_{uuid.uuid4().hex[:4]}.mp4"
        await file.download_to_drive(raw_path)
        
        out_path, s_type = await process_media_core(raw_path, user_id, not msg.photo)
        
        context.user_data["last_sticker_info"] = {"path": out_path, "type": s_type, "emoji": "✨"}
        
        if context.user_data.get("state") == "waiting_first_sticker":
            await create_pack_action(update, context)
        else:
            context.user_data["state"] = "waiting_emoji"
            with open(out_path, "rb") as f: await context.bot.send_sticker(user_id, f)
            await update.message.reply_text("😄 أرسل الإيموجي الآن:")
        
        await status.delete()
        if os.path.exists(raw_path): os.remove(raw_path)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def process_media_core(raw_path, user_id, is_video):
    out = f"out_{user_id}_{uuid.uuid4().hex[:4]}" + (".webm" if is_video else ".webp")
    if not is_video:
        img = Image.open(raw_path).convert("RGBA")
        img.thumbnail((512, 512), Image.LANCZOS)
        img.save(out, "WEBP")
        return out, StickerFormat.STATIC
    else:
        # تقليل الإعدادات لأقصى درجة لحل خطأ Sticker_video_nowallpaper
        clip = VideoFileClip(raw_path).subclip(0, 2.5)
        clip = clip.resize(width=512) if clip.w > clip.h else clip.resize(height=512)
        # تقليل الـ bitrate جداً لضمان القبول الفوري
        clip.write_videofile(out, codec="libvpx-vp9", fps=30, bitrate="150k", audio=False, logger=None, ffmpeg_params=['-pix_fmt', 'yuva420p'])
        clip.close()
        return out, StickerFormat.VIDEO

async def create_pack_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, info = update.effective_user.id, context.user_data.get("last_sticker_info")
    bot = await context.bot.get_me()
    full_name = f"st_{uuid.uuid4().hex[:5]}_{user_id}_by_{bot.username}"
    
    try:
        with open(info["path"], "rb") as f:
            stk = InputSticker(f, [info["emoji"]])
            await context.bot.create_new_sticker_set(user_id, full_name, context.user_data["temp_title"], [stk], info["type"])
        add_pack_to_db(user_id, full_name, context.user_data["temp_title"], info["type"].value)
        await update.message.reply_text(f"🎉 تم إنشاء الحزمة!\n t.me/addstickers/{full_name}", reply_markup=main_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ تليجرام: {e}\n(نصيحة: تأكد أن الفيديو أقصر من 3 ثوانٍ)")
    finally:
        if os.path.exists(info["path"]): os.remove(info["path"])
        context.user_data.clear()

async def add_to_existing_pack_action(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    user_id, info = update.effective_user.id, context.user_data.get("last_sticker_info")
    pack_title = text.replace("➕ إضافة إلى: ", "")
    real_name = next((p[0] for p in get_user_packs(user_id) if p[1] == pack_title), None)
    
    if real_name and info:
        try:
            with open(info["path"], "rb") as f:
                await context.bot.add_sticker_to_set(user_id, real_name, InputSticker(f, [info["emoji"]]))
            await update.message.reply_text("✅ تمت الإضافة!", reply_markup=main_menu())
        except Exception as e: await update.message.reply_text(f"❌ فشل: {e}")
        finally:
            if os.path.exists(info["path"]): os.remove(info["path"])
            context.user_data.clear()

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))
    app.run_polling(drop_pending_updates=True)
    
