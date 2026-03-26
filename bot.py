import os, json, uuid, asyncio, logging
from PIL import Image
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
STORE_FILE = "user_packs.json"

# --- نظام الحفظ ---
def load_db():
    if os.path.exists(STORE_FILE):
        try:
            with open(STORE_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_db(data):
    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

DB = load_db()

# --- معالجة الأبعاد 512x512 ---
def process_sticker_media(raw_path, is_video):
    out = f"final_{uuid.uuid4().hex[:6]}" + (".webm" if is_video else ".webp")
    if not is_video:
        img = Image.open(raw_path).convert("RGBA")
        canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        img.thumbnail((512, 512), Image.LANCZOS)
        canvas.paste(img, ((512 - img.width) // 2, (512 - img.height) // 2), img)
        canvas.save(out, "WEBP")
    else:
        clip = VideoFileClip(raw_path).subclip(0, 2.5)
        clip = clip.resize(width=512) if clip.w > clip.h else clip.resize(height=512)
        clip.write_videofile(out, codec="libvpx-vp9", fps=30, bitrate="150k", audio=False, logger=None, ffmpeg_params=['-pix_fmt', 'yuva420p'])
        clip.close()
    return out

# --- القوائم الرئيسية ---
def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 تحويل صورة"), KeyboardButton("🎥 تحويل فيديو / GIF")],
        [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("➕ ربط حزمة يدوياً")],
        [KeyboardButton("🗂️ حزمي")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🚀 أهلاً بك! جرب الآن 'إنشاء حزمة' أو 'ربط يدوي'.", reply_markup=main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text
    state = context.user_data.get("state")

    if text == "📸 تحويل صورة":
        context.user_data.update({"state": "wait_media", "mode": "photo"})
        await update.message.reply_text("📥 أرسل الصورة...")
    
    elif text == "🎥 تحويل فيديو / GIF":
        context.user_data.update({"state": "wait_media", "mode": "video"})
        await update.message.reply_text("📥 أرسل الفيديو...")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = "get_title"
        await update.message.reply_text("✍️ أرسل عنوان الحزمة بالعربي:")

    elif text == "➕ ربط حزمة يدوياً":
        context.user_data["state"] = "get_manual_link"
        await update.message.reply_text("🔗 أرسل (الاسم القصير) للحزمة فقط:")

    elif text == "🗂️ حزمي":
        packs = DB.get(user_id, [])
        if not packs: await update.message.reply_text("⚠️ لا توجد حزم.")
        else:
            m = "📚 حزمك:\n\n" + "\n".join([f"🔹 {p['title']}\n t.me/addstickers/{p['name']}" for p in packs])
            await update.message.reply_text(m)

    elif state == "get_title":
        context.user_data.update({"t_title": text, "state": "get_name"})
        await update.message.reply_text("🔗 أرسل اسم الرابط (بالإنجليزي):")

    elif state == "get_name":
        context.user_data.update({"t_name": "".join(e for e in text if e.isalnum()), "state": "wait_first"})
        await update.message.reply_text("✅ أرسل الآن الملصق الأول:")

    elif state == "get_manual_link":
        try:
            # تنظيف الرابط إذا أرسله المستخدم بالخطأ
            clean_name = text.split('/')[-1]
            p = await context.bot.get_sticker_set(clean_name)
            if user_id not in DB: DB[user_id] = []
            if not any(x['name'] == clean_name for x in DB[user_id]):
                DB[user_id].append({"name": clean_name, "title": p.title})
                save_db(DB)
            await update.message.reply_text(f"✅ تم ربط الحزمة: {p.title}", reply_markup=main_menu())
        except: await update.message.reply_text("❌ تأكد من الاسم القصير!")
        context.user_data["state"] = None

    elif state == "wait_emoji":
        context.user_data["emoji"] = text
        packs = DB.get(user_id, [])
        if packs:
            btns = [[KeyboardButton(f"➕ إضافة إلى: {p['title']}")] for p in packs]
            await update.message.reply_text(f"👍 اختر الحزمة:", reply_markup=ReplyKeyboardMarkup(btns, resize_keyboard=True))

    elif text.startswith("➕ إضافة إلى: "):
        await add_to_pack_final(update, context, text)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    msg = update.message
    media = msg.photo or msg.video or msg.animation or msg.video_note
    if not media: return

    try:
        status = await update.message.reply_text("⏳ جاري المعالجة...")
        raw = f"raw_{uuid.uuid4().hex[:4]}"
        file = await (media[-1].get_file() if msg.photo else media.get_file())
        await file.download_to_drive(raw)

        out = await asyncio.to_thread(process_sticker_media, raw, not msg.photo)
        fmt = StickerFormat.STATIC if msg.photo else StickerFormat.VIDEO
        context.user_data["pending"] = {"path": out, "format": fmt}

        if context.user_data.get("state") == "wait_first":
            await create_pack_final(update, context)
        else:
            context.user_data["state"] = "wait_emoji"
            with open(out, "rb") as f: await context.bot.send_sticker(user_id, f)
            await update.message.reply_text("😄 أرسل الإيموجي الآن:")
        
        await status.delete()
        if os.path.exists(raw): os.remove(raw)
    except Exception as e: await update.message.reply_text(f"❌ خطأ: {e}")

async def create_pack_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    info, bot = context.user_data["pending"], await context.bot.get_me()
    # اسم فريد لضمان عدم التكرار
    p_name = f"st_{context.user_data['t_name']}_{uuid.uuid4().hex[:4]}_by_{bot.username}"
    p_title = context.user_data["t_title"]

    try:
        with open(info["path"], "rb") as f:
            # الحل لـ Peer_id_invalid هو التأكد من إرسال الـ ID كرقم
            await context.bot.create_new_sticker_set(
                user_id=int(user_id), 
                name=p_name, 
                title=p_title, 
                stickers=[InputSticker(f, ["✨"])], 
                sticker_format=info["format"]
            )
        
        uid_s = str(user_id)
        if uid_s not in DB: DB[uid_s] = []
        DB[uid_s].append({"name": p_name, "title": p_title})
        save_db(DB)
        await update.message.reply_text(f"🎉 تم الإنشاء!\n t.me/addstickers/{p_name}", reply_markup=main_menu())
    except Exception as e: 
        await update.message.reply_text(f"❌ تليجرام رفض الطلب: {e}\n(تأكد أنك بدأت المحادثة مع البوت أولاً)")
    finally:
        if os.path.exists(info["path"]): os.remove(info["path"])
        context.user_data.clear()

async def add_to_pack_final(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    user_id, info = update.effective_user.id, context.user_data.get("pending")
    title = text.replace("➕ إضافة إلى: ", "")
    pack = next((p for p in DB.get(str(user_id), []) if p['title'] == title), None)

    if pack and info:
        try:
            with open(info["path"], "rb") as f:
                await context.bot.add_sticker_to_set(int(user_id), pack['name'], InputSticker(f, [context.user_data.get("emoji", "✨")]))
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
    
