import asyncio
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageOps

from telegram import Update, InputSticker
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

STATE_FILE = "data.json"

def load_data():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)

def resize_image(input_path, output_path):
    img = Image.open(input_path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGBA")
    img.thumbnail((512, 512))

    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    canvas.paste(img, ((512 - img.width)//2, (512 - img.height)//2))

    canvas.save(output_path, "WEBP")

def convert_video(input_path, output_path):
    subprocess.run([
        "ffmpeg",
        "-i", input_path,
        "-t", "3",
        "-vf", "scale=512:512",
        "-an",
        "-c:v", "libvpx-vp9",
        output_path
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📥 ارسل صورة او فيديو وانا احوله لستيكر")

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    if str(user.id) not in data:
        data[str(user.id)] = 1

    pack_num = data[str(user.id)]
    bot_username = (await context.bot.get_me()).username
    pack_name = f"pack_{user.id}_{pack_num}_by_{bot_username}"

    with tempfile.TemporaryDirectory() as tmp:
        input_file = os.path.join(tmp, "input")
        output_file = os.path.join(tmp, "output.webp")

        # تحميل
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            await file.download_to_drive(input_file)
            resize_image(input_file, output_file)
            sticker_type = "static"

        elif update.message.video or update.message.animation:
            file = await (update.message.video or update.message.animation).get_file()
            await file.download_to_drive(input_file)
            output_file = os.path.join(tmp, "output.webm")
            convert_video(input_file, output_file)
            sticker_type = "video"
        else:
            await update.message.reply_text("❌ ارسل صورة او فيديو فقط")
            return

        try:
            with open(output_file, "rb") as f:
                sticker = InputSticker(f, emoji_list=["🔥"])

                await context.bot.add_sticker_to_set(
                    user_id=user.id,
                    name=pack_name,
                    sticker=sticker
                )
        except:
            with open(output_file, "rb") as f:
                sticker = InputSticker(f, emoji_list=["🔥"])

                await context.bot.create_new_sticker_set(
                    user_id=user.id,
                    name=pack_name,
                    title=f"Pack {pack_num}",
                    stickers=[sticker]
                )

            data[str(user.id)] += 1
            save_data(data)

        await update.message.reply_text(f"✅ تم الإضافة\nhttps://t.me/addstickers/{pack_name}")

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    print("Bot running...")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
