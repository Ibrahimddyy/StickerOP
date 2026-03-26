import os, json, uuid, asyncio, logging
from PIL import Image
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputSticker
from telegram.constants import StickerFormat
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# إعداد السجلات لمراقبة الأداء في ريلوي
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from moviepy.editor import VideoFileClip
except:
    try: from moviepy import VideoFileClip
    except: from moviepy.video.io.VideoFileClip import VideoFileClip

TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = "user_database.json"

# --- نظام تخزين البيانات ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

DB = load_db()

# --- معالجة الصور والفيديو (معيار 512x512) ---
def process_media(input_path, is_video=False):
    output_path = f"final_{uuid.uuid4().hex[:6]}" + (".webm" if is_video else ".png")
    
    if not is_video:
        with Image.open(input_path) as img:
            img = img.convert("RGBA")
            img.thumbnail((512, 512), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
            canvas.paste(img, ((512 - img.width) // 2, (512 - img.height) // 2), img)
            canvas.save(output_path, "PNG")
    else:
        clip = VideoFileClip(input_path).subclip(0, 2.8)
        # ضبط الحجم ليكون الضلع الأكبر 512
        w, h = clip.size
        if w > h: clip = clip.resize(width=512)
        else: clip = clip.resize(height=512)
        
        clip.write_videofile(output_path, codec="libvpx-vp9", fps=30, bitrate="150k", audio=False, logger=None, ffmpeg_params=['-pix_fmt', 'yuva420p'])
        clip.close()
    
    return output_path

# --- القوائم ---
def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🖼️ صنع ملصق (صورة)"), KeyboardButton("🎬 صنع ملصق (فيديو)")],
        [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("➕ ربط حزمة يدوياً")],
        [KeyboardButton("🗂️ عرض حزمي")]
    ], resize_keyboard=True)

# --- معالجة الأوامر ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلاً بك في بوت الملصقات المطور!\nاختر ما تريد فعله:", reply_markup=main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text
    state = context.user_data.get("state")

    if text == "🖼️ صنع ملصق (صورة)":
        context.user_data.update({"state": "wait_media", "mode": "photo"})
        await update.message.reply_text("📥 أرسل الصورة الآن...")
    
    elif text == "🎬 صنع ملصق (فيديو)":
        context.user_data.update({"state": "wait_media", "mode": "video"})
        await update.message.reply_text("📥 أرسل الفيديو أو الـ GIF...")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = "get_title"
        await update.message.reply_text("✍️ أرسل اسم الحزمة (بالعربي):")

    elif text == "➕ ربط حزمة يدوياً":
        context.user_data["state"] = "link_manual"
        await update.message.reply_text("🔗 أرسل (الاسم القصير) للحزمة لربطها:")

    elif text == "🗂️ عرض حزمي":
        packs = DB.get(user_id, [])
        if not packs: await update.message.reply_text("⚠️ لا توجد حزم محفوظة.")
        else:
            msg = "📚 حزمك النشطة:\n\n" + "\n".join([f"🔹 {p['title']}\n t.me/addstickers/{p['name']}" for p in packs])
            await update.message.reply_text(msg)

    # --- إدارة التدفق ---
    elif state == "get_title":
        context.user_data.update({"t_title": text, "state": "get_short_name"})
        await update.message.reply_text("🔗 أرسل اسم الرابط (إنجليزي فقط):")

    elif state == "get_short_name":
        clean_name = "".join(e for e in text if e.isalnum())
        context.user_data.update({"t_name": clean_name, "state": "wait_first_sticker"})
        await update.message.reply_text(f"✅ تم! الآن أرسل (أول ملصق) لإنشاء الحزمة باسم '{clean_name}':")

    elif state == "link_manual":
        short_name = text.split('/')[-1]
        try:
            p = await context.bot.get_sticker_set(short_name)
            if user_id not in DB: DB[user_id] = []
            if not any(x['name'] == short_name for x in DB[user_id]):
                DB[user_id].append({"name": short_name, "title": p.title})
                save_db(DB)
            await update.message.reply_text(f"✅ تم ربط الحزمة: {p.title}", reply_markup=main_menu())
        except: await update.message.reply_text("❌ لم أجد هذه الحزمة، تأكد من الاسم!")
        context.user_data["state"] = None

    elif state == "wait_emoji":
        context.user_data["emoji"] = text
        packs = DB.get(user_id, [])
        if packs:
            btns = [[KeyboardButton(f"➕ إضافة إلى: {p['title']}")] for p in packs]
            await update.message.reply_text("🎯 اختر الحزمة التي تريد الإضافة إليها:", reply_markup=ReplyKeyboardMarkup(btns, resize_keyboard=True))
        else:
            await update.message.reply_text("⚠️ ليس لديك حزم! أنشئ واحدة أولاً.")

    elif text.startswith("➕ إضافة إلى: "):
        await add_to_pack(update, context)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    media = msg.photo or msg.video or msg.animation or msg.video_note
    if not media: return

    try:
        prog = await update.message.reply_text("⏳ جاري المعالجة الفنية...")
        raw = f"temp_{uuid.uuid4().hex[:4]}"
        file = await (media[-1].get_file() if msg.photo else media.get_file())
        await file.download_to_drive(raw)

        is_vid = not msg.photo
        out = await asyncio.to_thread(process_media, raw, is_vid)
        
        context.user_data["pending"] = {"path": out, "format": StickerFormat.VIDEO if is_vid else StickerFormat.STATIC}
        
        if context.user_data.get("state") == "wait_first_sticker":
            await create_pack(update, context)
        else:
            context.user_data["state"] = "wait_emoji"
            with open(out, "rb") as f: await context.bot.send_sticker(update.effective_user.id, f)
            await update.message.reply_text("✨ الملصق جاهز! أرسل الإيموجي الآن:")
        
        await prog.delete()
        if os.path.exists(raw): os.remove(raw)
    except Exception as e: await update.message.reply_text(f"❌ خطأ تقني: {e}")

async def create_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    info = context.user_data["pending"]
    bot = await context.bot.get_me()
    p_name = f"st_{context.user_data['t_name']}_{uuid.uuid4().hex[:4]}_by_{bot.username}"
    p_title = context.user_data["t_title"]

    try:
        with open(info["path"], "rb") as f:
            await context.bot.create_new_sticker_set(
                user_id=int(user_id), name=p_name, title=p_title,
                stickers=[InputSticker(f, ["✨"])], sticker_format=info["format"]
            )
        
        uid = str(user_id)
        if uid not in DB: DB[uid] = []
        DB[uid].append({"name": p_name, "title": p_title})
        save_db(DB)
        await update.message.reply_text(f"🎉 مبارك! تم إنشاء حزمتك:\nt.me/addstickers/{p_name}", reply_markup=main_menu())
    except Exception as e: await update.message.reply_text(f"❌ تليجرام رفض الإنشاء: {e}")
    finally:
        if os.path.exists(info["path"]): os.remove(info["path"])
        context.user_data.clear()

async def add_to_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    info = context.user_data.get("pending")
    title = update.message.text.replace("➕ إضافة إلى: ", "")
    pack = next((p for p in DB.get(user_id, []) if p['title'] == title), None)

    if pack and info:
        try:
            with open(info["path"], "rb") as f:
                await context.bot.add_sticker_to_set(int(user_id), pack['name'], InputSticker(f, [context.user_data.get("emoji", "✨")]))
            await update.message.reply_text("✅ تمت الإضافة بنجاح!", reply_markup=main_menu())
        except Exception as e: await update.message.reply_text(f"❌ فشل الإضافة: {e}")
        finally:
            if os.path.exists(info["path"]): os.remove(info["path"])
            context.user_data.clear()

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))
    app.run_polling(drop_pending_updates=True)
            
