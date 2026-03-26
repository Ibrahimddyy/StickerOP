import os, json, uuid, asyncio, logging
from PIL import Image, ImageOps
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputSticker
from telegram.constants import StickerFormat
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# إعداد السجلات لمراقبة الأخطاء
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# محاولة تحميل مكتبة الفيديو
try:
    from moviepy.editor import VideoFileClip
except:
    try: from moviepy import VideoFileClip
    except: from moviepy.video.io.VideoFileClip import VideoFileClip

TOKEN = os.getenv("BOT_TOKEN")
STORE_FILE = "sticker_packs.json"

# -------------------- نظام التخزين المستقر --------------------
def load_store():
    if os.path.exists(STORE_FILE):
        with open(STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_store(data):
    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

PACKS_STORE = load_store()

def add_user_pack(user_id, name, title, pack_type):
    user_id = str(user_id)
    if user_id not in PACKS_STORE: PACKS_STORE[user_id] = []
    # منع التكرار
    if not any(p['name'] == name for p in PACKS_STORE[user_id]):
        PACKS_STORE[user_id].append({"name": name, "title": title, "type": pack_type})
        save_store(PACKS_STORE)

# -------------------- الواجهة والأزرار --------------------
def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📸 تحويل صورة"), KeyboardButton("🎥 تحويل فيديو / GIF")],
        [KeyboardButton("📦 إنشاء حزمة جديدة"), KeyboardButton("➕ إضافة حزمة يدوياً")],
        [KeyboardButton("🗂️ حزمي")]
    ], resize_keyboard=True)

# -------------------- معالجة الميديا (الدقة العالية) --------------------
def process_image(raw_path):
    out = f"out_{uuid.uuid4().hex[:8]}.webp"
    img = Image.open(raw_path).convert("RGBA")
    # جعل الصورة داخل مربع 512x512 مع الحفاظ على الأبعاد
    img.thumbnail((512, 512), Image.LANCZOS)
    img.save(out, "WEBP")
    return out

def process_video(raw_path):
    out = f"out_{uuid.uuid4().hex[:8]}.webm"
    clip = VideoFileClip(raw_path).subclip(0, 2.5) # أقل من 3 ثواني إجباري
    if clip.w > clip.h: clip = clip.resize(width=512)
    else: clip = clip.resize(height=512)
    
    # إعدادات الـ Bitrate والـ Pix_fmt لحل خطأ nowallpaper
    clip.write_videofile(out, codec="libvpx-vp9", fps=30, bitrate="150k", audio=False, logger=None, ffmpeg_params=['-pix_fmt', 'yuva420p'])
    clip.close()
    return out

# -------------------- الأوامر الأساسية --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("👋 أهلاً بك في بوت الملصقات المطور!\nاختر من القائمة للبدء:", reply_markup=main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get("state")

    if text == "📸 تحويل صورة":
        context.user_data.update({"state": "waiting_media", "mode": "photo"})
        await update.message.reply_text("📥 أرسل الصورة الآن...")
    
    elif text == "🎥 تحويل فيديو / GIF":
        context.user_data.update({"state": "waiting_media", "mode": "video"})
        await update.message.reply_text("📥 أرسل الفيديو (أقل من 3 ثوانٍ)...")

    elif text == "📦 إنشاء حزمة جديدة":
        context.user_data["state"] = "waiting_pack_title"
        await update.message.reply_text("✍️ أرسل عنوان الحزمة (بالعربي مثلاً):")

    elif text == "➕ إضافة حزمة يدوياً":
        context.user_data["state"] = "waiting_manual_link"
        await update.message.reply_text("🔗 أرسل اسم الحزمة (الرابط القصير):")

    elif text == "🗂️ حزمي":
        packs = PACKS_STORE.get(str(user_id), [])
        if not packs: await update.message.reply_text("⚠️ لا توجد حزم محفوظة.")
        else:
            msg = "📚 حزمك النشطة:\n\n" + "\n".join([f"🔹 {p['title']}: t.me/addstickers/{p['name']}" for p in packs])
            await update.message.reply_text(msg)

    # --- حالات إنشاء حزمة ---
    elif state == "waiting_pack_title":
        context.user_data.update({"temp_title": text, "state": "waiting_pack_name"})
        await update.message.reply_text("🔗 أرسل اسم الرابط (بالإنجليزي):")

    elif state == "waiting_pack_name":
        # تنظيف الاسم وإضافة كود فريد لضمان النجاح
        clean_name = "".join(e for e in text if e.isalnum())
        context.user_data.update({"temp_name": clean_name, "state": "waiting_first_media"})
        await update.message.reply_text("✅ رائع! الآن أرسل (الملصق الأول) لتفعيل الحزمة:")

    elif state == "waiting_manual_link":
        try:
            pack = await context.bot.get_sticker_set(text)
            add_user_pack(user_id, text, pack.title, "static") # افتراضي
            await update.message.reply_text(f"✅ تم حفظ الحزمة: {pack.title}", reply_markup=main_menu())
        except: await update.message.reply_text("❌ لم أجد هذه الحزمة، تأكد من الاسم.")
        context.user_data["state"] = None

    elif state == "waiting_emoji":
        # هنا مرحلة الإيموجي - تم إصلاحها لتعمل مع الذاكرة
        context.user_data["selected_emoji"] = text
        packs = PACKS_STORE.get(str(user_id), [])
        if not packs:
            await update.message.reply_text("⚠️ لا تملك حزم! اضغط إنشاء حزمة.")
        else:
            context.user_data["state"] = "selecting_pack"
            btns = [[KeyboardButton(f"➕ إضافة إلى: {p['title']}")] for p in packs]
            await update.message.reply_text(f"👍 تم اختيار {text}. اختر الحزمة:", reply_markup=ReplyKeyboardMarkup(btns, resize_keyboard=True))

    elif text.startswith("➕ إضافة إلى: "):
        await add_to_pack_logic(update, context, text)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("state")
    msg = update.message
    media = msg.photo or msg.video or msg.animation or msg.video_note
    if not media: return

    try:
        status = await update.message.reply_text("⏳ جاري المعالجة الاحترافية...")
        file = await (media[-1].get_file() if msg.photo else media.get_file())
        raw_path = f"raw_{uuid.uuid4().hex[:4]}"
        await file.download_to_drive(raw_path)

        # تحويل الميديا
        if msg.photo:
            out_path = await asyncio.to_thread(process_image, raw_path)
            s_format = StickerFormat.STATIC
        else:
            out_path = await asyncio.to_thread(process_video, raw_path)
            s_format = StickerFormat.VIDEO

        context.user_data["pending_sticker"] = {"path": out_path, "format": s_format}

        if state == "waiting_first_media":
            await create_pack_logic(update, context)
        else:
            context.user_data["state"] = "waiting_emoji"
            with open(out_path, "rb") as f: await context.bot.send_sticker(user_id, f)
            await update.message.reply_text("😄 ملصقك جاهز! أرسل (الإيموجي) الآن:")
        
        await status.delete()
        if os.path.exists(raw_path): os.remove(raw_path)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def create_pack_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    info = context.user_data["pending_sticker"]
    bot = await context.bot.get_me()
    
    # اسم الرابط فريد جداً
    full_name = f"st_{context.user_data['temp_name']}_{uuid.uuid4().hex[:4]}_by_{bot.username}"
    title = context.user_data["temp_title"]

    try:
        with open(info["path"], "rb") as f:
            stk = InputSticker(f, ["✨"]) # إيموجي افتراضي لأول ملصق
            await context.bot.create_new_sticker_set(
                user_id=user_id, name=full_name, title=title, 
                stickers=[stk], sticker_format=info["format"]
            )
        add_user_pack(user_id, full_name, title, info["format"].value)
        await update.message.reply_text(f"🎉 تم إنشاء الحزمة!\n t.me/addstickers/{full_name}", reply_markup=main_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ فشل تليجرام: {e}")
    finally:
        if os.path.exists(info["path"]): os.remove(info["path"])
        context.user_data.clear()

async def add_to_pack_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    user_id = update.effective_user.id
    info = context.user_data.get("pending_sticker")
    emoji = context.user_data.get("selected_emoji", "✨")
    
    selected_title = text.replace("➕ إضافة إلى: ", "")
    packs = PACKS_STORE.get(str(user_id), [])
    pack_name = next((p['name'] for p in packs if p['title'] == selected_title), None)

    if pack_name and info:
        try:
            with open(info["path"], "rb") as f:
                await context.bot.add_sticker_to_set(user_id, pack_name, InputSticker(f, [emoji]))
            await update.message.reply_text("✅ تمت الإضافة بنجاح!", reply_markup=main_menu())
        except Exception as e:
            await update.message.reply_text(f"❌ فشل: {e}\n(ملاحظة: لا يمكنك خلط الصور والفيديوهات في حزمة واحدة)")
        finally:
            if os.path.exists(info["path"]): os.remove(info["path"])
            context.user_data.clear()

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_media))
    app.run_polling(drop_pending_updates=True)
    
