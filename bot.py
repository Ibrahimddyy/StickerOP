import os
import json
from PIL import Image
from rembg import remove
from moviepy.editor import VideoFileClip
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

DATA_FILE = "data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

users = load_data()
temp = {}

def keyboard():
    return ReplyKeyboardMarkup([
        ["📸 صورة", "🎥 فيديو"],
        ["🎨 إزالة خلفية", "🧠 ايموجي تلقائي"],
        ["📦 حزماتي", "📊 احصائياتي"]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔥 النسخة الخارقة جاهزة!", reply_markup=keyboard())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    text = update.message.text

    temp.setdefault(user_id, {})

    if text == "📸 صورة":
        temp[user_id]["mode"] = "photo"
        await update.message.reply_text("ارسل الصورة")

    elif text == "🎥 فيديو":
        temp[user_id]["mode"] = "video"
        await update.message.reply_text("ارسل الفيديو")

    elif text == "🎨 إزالة خلفية":
        temp[user_id]["remove_bg"] = True
        await update.message.reply_text("تم تفعيل إزالة الخلفية")

    elif text == "🧠 ايموجي تلقائي":
        temp[user_id]["auto_emoji"] = True
        await update.message.reply_text("تم تفعيل الذكاء")

    elif temp[user_id].get("wait_emoji"):
        temp[user_id]["emoji"] = text
        temp[user_id]["wait_emoji"] = False
        await process(update, context, user_id)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    file = await update.message.photo[-1].get_file()
    path = f"{user_id}.jpg"
    await file.download_to_drive(path)

    temp[user_id]["file"] = path

    if temp[user_id].get("auto_emoji"):
        temp[user_id]["emoji"] = "🔥"
        await process(update, context, user_id)
    else:
        temp[user_id]["wait_emoji"] = True
        await update.message.reply_text("اختار ايموجي 😊")
        async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    file = await update.message.video.get_file()
    path = f"{user_id}.mp4"
    await file.download_to_drive(path)

    temp[user_id]["file"] = path
    temp[user_id]["is_video"] = True

    if temp[user_id].get("auto_emoji"):
        temp[user_id]["emoji"] = "🔥"
        await process(update, context, user_id)
    else:
        temp[user_id]["wait_emoji"] = True
        await update.message.reply_text("اختار ايموجي 😊")

async def process(update, context, user_id):
    data = temp[user_id]
    path = data["file"]
    emoji = data.get("emoji", "😄")

    if data.get("is_video"):
        clip = VideoFileClip(path).subclip(0, 3)
        out = f"{user_id}.webm"
        clip.write_videofile(out, codec="libvpx", audio=False)
    else:
        img = Image.open(path)

        if data.get("remove_bg"):
            img = remove(img)

        img = img.resize((512, 512))
        out = f"{user_id}.webp"
        img.save(out, "WEBP")

    await context.bot.send_sticker(
        chat_id=update.effective_chat.id,
        sticker=open(out, "rb")
    )

    users.setdefault(user_id, {"count": 0})
    users[user_id]["count"] += 1
    save_data(users)

    await update.message.reply_text(f"تم الإنشاء 🔥 الإيموجي: {emoji}")

    os.remove(path)
    os.remove(out)
    temp[user_id] = {}

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT, text_handler))
app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
app.add_handler(MessageHandler(filters.VIDEO, video_handler))

app.run_polling()
