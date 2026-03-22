import os
import json
from PIL import Image
from moviepy.editor import VideoFileClip

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "data.json"

users = {}
temp = {}

# ===== keyboard =====
def keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📸 صورة", "🎥 فيديو"],
            ["🧠 ايموجي تلقائي", "📊 احصائياتي"]
        ],
        resize_keyboard=True
    )

# ===== start =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 بوت ستيكر شغال\nاختار من القائمة:",
        reply_markup=keyboard()
    )

# ===== text =====
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    text = update.message.text

    if user_id not in temp:
        temp[user_id] = {}

    if text == "📸 صورة":
        temp[user_id]["mode"] = "photo"
        await update.message.reply_text("ارسل الصورة")

    elif text == "🎥 فيديو":
        temp[user_id]["mode"] = "video"
        await update.message.reply_text("ارسل الفيديو")

    elif text == "🧠 ايموجي تلقائي":
        temp[user_id]["auto"] = True
        await update.message.reply_text("تم تفعيل الايموجي التلقائي")

    elif text == "📊 احصائياتي":
        count = users.get(user_id, 0)
        await update.message.reply_text(f"عدد الستيكرات: {count}")

    elif temp[user_id].get("wait"):
        temp[user_id]["emoji"] = text
        temp[user_id]["wait"] = False
        await process(update, context, user_id)

# ===== photo =====
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    if temp.get(user_id, {}).get("mode") != "photo":
        return

    file = await update.message.photo[-1].get_file()
    path = f"{user_id}.jpg"
    await file.download_to_drive(path)

    temp[user_id]["file"] = path

    if temp[user_id].get("auto"):
        temp[user_id]["emoji"] = "🔥"
        await process(update, context, user_id)
    else:
        temp[user_id]["wait"] = True
        await update.message.reply_text("ارسل ايموجي")

# ===== video =====
async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    if temp.get(user_id, {}).get("mode") != "video":
        return

    file = await update.message.video.get_file()
    path = f"{user_id}.mp4"
    await file.download_to_drive(path)

    temp[user_id]["file"] = path
    temp[user_id]["video"] = True

    if temp[user_id].get("auto"):
        temp[user_id]["emoji"] = "🔥"
        await process(update, context, user_id)
    else:
        temp[user_id]["wait"] = True
        await update.message.reply_text("ارسل ايموجي")

# ===== process =====
async def process(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    data = temp[user_id]
    path = data["file"]
    emoji = data.get("emoji", "😄")

    try:
        if data.get("video"):
            clip = VideoFileClip(path).subclip(0, 3)
            out = f"{user_id}.webm"
            clip.write_videofile(out, codec="libvpx", audio=False)
        else:
            img = Image.open(path)
            img = img.resize((512, 512))
            out = f"{user_id}.webp"
            img.save(out, "WEBP")

        await context.bot.send_sticker(
            chat_id=update.effective_chat.id,
            sticker=open(out, "rb")
        )

        users[user_id] = users.get(user_id, 0) + 1

        await update.message.reply_text(f"تم الستيكر {emoji}")

    except Exception as e:
        await update.message.reply_text(str(e))

    finally:
        if os.path.exists(path):
            os.remove(path)
        if 'out' in locals() and os.path.exists(out):
            os.remove(out)

        temp[user_id] = {}

# ===== run =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT, text_handler))
app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
app.add_handler(MessageHandler(filters.VIDEO, video_handler))

print("RUNNING...")

app.run_polling()
