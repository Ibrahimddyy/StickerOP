import os, json, uuid, asyncio, logging
from PIL import Image, ImageOps
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputSticker
from telegram.constants import StickerFormat
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from moviepy.editor import VideoFileClip
except:
    try: from moviepy import VideoFileClip
    except: from moviepy.video.io.VideoFileClip import VideoFileClip

TOKEN = os.getenv("BOT_TOKEN")
STORE_FILE = "packs_data.json"

# --- التخزين ---
def load_data():
    if os.path.exists(STORE_FILE):
        with open(STORE_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return {}

def save_data(data):
    with open(STORE_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

USER_DATA_STORE = load_data()

# --- الواجهة ---
def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 تحويل صورة"), KeyboardButton("🎥 تحويل فيديو / GIF")],
        [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("🗂️ حزمي")]
    ], resize_keyboard=True)

# --- المعالجة (حل مشكلة الأبعاد 512x512) ---
def final_process_image(raw_path):
    out = f"final_{uuid.uuid4().hex[:6]}.webp"
    img = Image.open(raw_path).convert("RGBA")
    
    # صنع لوحة شفافة 512x512 بالضبط
    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    img.thumbnail((512, 512), Image.LANCZOS)
    
    # وضع الصورة في المنتصف
    offset = ((512 - img.width) // 2, (512 - img.height) // 2)
    canvas.paste(img, offset, img)
    canvas.save(out, "WEBP")
    return out

def final_process_video(raw_path):
    out = f"final_{uuid.uuid4().hex[:6]}.webm"
    clip = VideoFileClip(raw_path).subclip(0, 2.5)
    
    # ضبط الفيديو ليكون داخل إطار 512x512
    if clip.w > clip.h: clip = clip.resize(width=512)
    else: clip = clip.resize(height=512)
    
    clip.write_videofile(out, codec="libvpx-vp9", fps=30, bitrate="150k", audio=False, logger=None, ffmpeg_params=['-pix_fmt', 'yuva420p'])
    clip.close()
    return out

# --- المنطق الأساسي ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🚀 تم تحديث البوت لإصلاح أخطاء تليجرام. اختر الآن:", reply_markup=main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, text = update.effective_user.id, update.message.text
    state = context.user_data.get("state")

    if text == "📸 تحويل صورة":
        context.user_data.update({"state": "waiting_media", "mode": "photo"})
        await update.message.reply_text("📥 أرسل الصورة...")
    
    elif text == "🎥 تحويل فيديو / GIF":
        context.user_data.update({"state": "waiting_media", "mode": "video"})
        await update.message.reply_text("📥 أرسل الفيديو...")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = "get_title"
        await update.message.reply_text("✍️ أرسل عنوان الحزمة (بالعربي):")

    elif text == "🗂️ حزمي":
        packs = USER_DATA_STORE.get(str(user_id), [])
        msg = "📚 حزمك:\n\n" + "\n".join([f"🔹 {p['title']}: t.me/addstickers/{p['name']}" for p in packs]) if packs else "⚠️ لا توجد حزم."
        await update.message.reply_text(msg)

    elif state == "get_title":
        context.user_data.update({"t_title": text, "state": "get_name"})
        await update.message.reply_text("🔗 أرسل اسم الرابط (بالإنجليزي):")

    elif state == "get_name":
        context.user_data.update({"t_name": "".join(e for e in text if e.isalnum()), "state": "waiting_first"})
        await update.message.reply_text("✅ أرسل الآن الملصق الأول لتفعيل الحزمة:")

    elif state == "waiting_emoji":
        context.user_data["emoji"] = text
        packs = USER_DATA_STORE.get(str(user_id), [])
        if packs:
            btns = [[KeyboardButton(f"➕ إضافة إلى: {p['title']}")] for p in packs]
            await update.message.reply_text(f"👍 اختر الحزمة:", reply_markup=ReplyKeyboardMarkup(btns, resize_keyboard=True))

    elif text.startswith("➕ إضافة إلى: "):
        await add_to_pack(update, context, text)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message
    media = msg.photo or msg.video or msg.animation or msg.video_note
    if not media: return

    try:
        status = await update.message.reply_text("⏳ جاري المعالجة...")
        raw = f"raw_{uuid.uuid4().hex[:4]}"
        file = await (media[-1].get_file() if msg.photo else media.get_file())
        await file.download_to_drive(raw)

        # المعالجة (تضمن 512x512)
        out = final_process_image(raw) if msg.photo else final_process_video(raw)
        fmt = StickerFormat.STATIC if msg.photo else StickerFormat.VIDEO
        
        context.user_data["pending"] = {"path": out, "format": fmt}
        
        if context.user_data.get("state") == "waiting_first":
            await create_pack(update, context)
        else:
            context.user_data["state"] = "waiting_emoji"
            with open(out, "rb") as f: await context.bot.send_sticker(user_id, f)
            await update.message.reply_text("😄 أرسل الإيموجي الآن:")
        
        await status.delete()
        if os.path.exists(raw): os.remove(raw)
    except Exception as e: await update.message.reply_text(f"❌ خطأ: {e}")

async def create_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    info = context.user_data["pending"]
    bot_info = await context.bot.get_me()
    
    # بناء اسم فريد جداً لتجنب الرفض
    p_name = f"st_{context.user_data['t_name']}_{uuid.uuid4().hex[:4]}_by_{bot_info.username}"
    p_title = context.user_data["t_title"]

    try:
        with open(info["path"], "rb") as f:
            await context.bot.create_new_sticker_set(
                user_id=user_id, name=p_name, title=p_title, 
                stickers=[InputSticker(f, ["✨"])], sticker_format=info["format"]
            )
        
        # حفظ الحزمة
        if str(user_id) not in USER_DATA_STORE: USER_DATA_STORE[str(user_id)] = []
        USER_DATA_STORE[str(user_id)].append({"name": p_name, "title": p_title})
        save_data(USER_DATA_STORE)
        
        await update.message.reply_text(f"🎉 تم الإنشاء!\n t.me/addstickers/{p_name}", reply_markup=main_menu())
    except Exception as e: await update.message.reply_text(f"❌ تليجرام رفض: {e}")
    finally:
        if os.path.exists(info["path"]): os.remove(info["path"])
        context.user_data.clear()

async def add_to_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    user_id, info = update.effective_user.id, context.user_data.get("pending")
    title = text.replace("➕ إضافة إلى: ", "")
    pack = next((p for p in USER_DATA_STORE.get(str(user_id), []) if p['title'] == title), None)

    if pack and info:
        try:
            with open(info["path"], "rb") as f:
                await context.bot.add_sticker_to_set(user_id, pack['name'], InputSticker(f, [context.user_data.get("emoji", "✨")]))
            await update.message.reply_text("✅ تمت الإضافة!", reply_markup=main_menu())
        except Exception as e: await update.message.reply_text(f"❌ فشل: {e}")
        finally:
            if os.path.exists(info["path"]): os.remove(info["path"])
            context.user_data.clear()

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))
    app.run_polling(drop_pending_updates=True)
    
