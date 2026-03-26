import os, json, uuid, logging
from PIL import Image
from telegram import Update, InputSticker
from telegram.constants import StickerFormat
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# إعداد التنبيهات لرؤية الأخطاء في Railway Logs
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = "packs.json"

def get_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: return json.load(f)
    return {}

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f)

@asyncio_handler
async def start(update, context):
    await update.message.reply_text("👋 أرسل صورة لتحويلها ملصق، أو استخدم /new لإنشاء حزمة.")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    status = await update.message.reply_text("⏳ جاري تجهيز الملصق...")
    
    # 1. تحميل ومعالجة الصورة لتكون 512x512 بالضبط
    raw_path = f"img_{user_id}.jpg"
    final_path = f"sticker_{user_id}.png"
    
    file = await photo.get_file()
    await file.download_to_drive(raw_path)
    
    with Image.open(raw_path) as img:
        img.thumbnail((512, 512), Image.Resampling.LANCZOS)
        pad = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        pad.paste(img, ((512 - img.width) // 2, (512 - img.height) // 2))
        pad.save(final_path, "PNG")

    context.user_data["path"] = final_path
    await status.edit_text("✅ الملصق جاهز! أرسل الآن الإيموجي (مثلاً 😄)")

async def handle_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "path" not in context.user_data: return
    
    user_id = update.effective_user.id
    emoji = update.message.text
    path = context.user_data["path"]
    bot = await context.bot.get_me()
    db = get_db()
    
    # محاولة إضافة أو إنشاء
    user_packs = db.get(str(user_id), [])
    
    if not user_packs:
        # إنشاء حزمة جديدة تلقائياً إذا ما عنده
        pack_name = f"pack_{user_id}_{uuid.uuid4().hex[:5]}_by_{bot.username}"
        try:
            with open(path, "rb") as f:
                success = await context.bot.create_new_sticker_set(
                    user_id=user_id,
                    name=pack_name,
                    title=f"حزمة {update.effective_user.first_name}",
                    stickers=[InputSticker(f, [emoji])],
                    sticker_format=StickerFormat.STATIC
                )
            if success:
                db[str(user_id)] = [{"name": pack_name, "title": "حزمتي الأولى"}]
                save_db(db)
                await update.message.reply_text(f"🎉 تم إنشاء حزمتك الأولى!\nhttps://t.me/addstickers/{pack_name}")
        except Exception as e:
            await update.message.reply_text(f"❌ فشل إنشاء الحزمة: {str(e)}")
    else:
        # إضافة للحزمة الموجودة
        p_name = user_packs[0]["name"]
        try:
            with open(path, "rb") as f:
                await context.bot.add_sticker_to_set(
                    user_id=user_id,
                    name=p_name,
                    sticker=InputSticker(f, [emoji])
                )
            await update.message.reply_text(f"✅ تم الإضافة لـ {p_name}")
        except Exception as e:
            await update.message.reply_text(f"❌ فشل الإضافة: {str(e)}")

    if os.path.exists(path): os.remove(path)
    context.user_data.clear()

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_emoji))
    app.run_polling()
    
