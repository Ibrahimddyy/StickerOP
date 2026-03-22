import asyncio
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputSticker
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "data.json"

logging.basicConfig(level=logging.INFO)

# ================== DATA ==================
def load():
    if not os.path.exists(DATA_FILE):
        return {}
    return json.load(open(DATA_FILE))

def save(data):
    json.dump(data, open(DATA_FILE, "w"))

# ================== TOOLS ==================
def resize(img_path, out):
    img = Image.open(img_path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGBA")
    img.thumbnail((512, 512))

    bg = Image.new("RGBA", (512, 512), (0,0,0,0))
    bg.paste(img, ((512-img.width)//2, (512-img.height)//2))
    bg.save(out, "WEBP")

def video_convert(inp, out):
    subprocess.run([
        "ffmpeg","-i",inp,
        "-t","3",
        "-vf","scale=512:512",
        "-an",
        "-c:v","libvpx-vp9",
        out
    ])

# ================== START ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📊 احصائياتي", callback_data="stats")],
        [InlineKeyboardButton("📦 حزماتي", callback_data="packs")]
    ]
    await update.message.reply_text(
        "🔥 بوت صناعة ستيكر احترافي\n\nارسل صورة او فيديو 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================== HANDLE MEDIA ==================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    data = load()

    if str(user.id) not in data:
        data[str(user.id)] = {"pack":1,"count":0,"emoji":"🔥"}

    kb = [
        [InlineKeyboardButton("😀", callback_data="emoji_😀"),
         InlineKeyboardButton("😂", callback_data="emoji_😂"),
         InlineKeyboardButton("🔥", callback_data="emoji_🔥")],
        [InlineKeyboardButton("✔️ تأكيد", callback_data="ok")]
    ]

    context.user_data["file"] = msg
    await msg.reply_text("اختر ايموجي:", reply_markup=InlineKeyboardMarkup(kb))

# ================== BUTTONS ==================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user = update.effective_user
    data = load()

    if q.data.startswith("emoji_"):
        emoji = q.data.split("_")[1]
        context.user_data["emoji"] = emoji
        await q.edit_message_text(f"تم اختيار {emoji}")

    elif q.data == "ok":
        msg = context.user_data.get("file")
        emoji = context.user_data.get("emoji","🔥")

        pack_num = data[str(user.id)]["pack"]
        bot_name = (await context.bot.get_me()).username
        pack = f"pack_{user.id}_{pack_num}_by_{bot_name}"

        with tempfile.TemporaryDirectory() as tmp:
            inp = os.path.join(tmp,"in")
            out = os.path.join(tmp,"out.webp")

            if msg.photo:
                f = await msg.photo[-1].get_file()
                await f.download_to_drive(inp)
                resize(inp,out)
            else:
                f = await (msg.video or msg.animation).get_file()
                await f.download_to_drive(inp)
                out = os.path.join(tmp,"out.webm")
                video_convert(inp,out)

            try:
                with open(out,"rb") as s:
                    sticker = InputSticker(s,emoji_list=[emoji])
                    await context.bot.add_sticker_to_set(user.id,pack,sticker)
            except:
                with open(out,"rb") as s:
                    sticker = InputSticker(s,emoji_list=[emoji])
                    await context.bot.create_new_sticker_set(
                        user.id,pack,f"Pack {pack_num}",[sticker]
                    )
                data[str(user.id)]["pack"]+=1

        data[str(user.id)]["count"]+=1
        save(data)

        await q.message.reply_text(f"✅ تم\nhttps://t.me/addstickers/{pack}")

    elif q.data == "stats":
        d = data.get(str(user.id),{})
        await q.edit_message_text(
            f"📊 احصائياتك\n\n"
            f"عدد الستيكرات: {d.get('count',0)}\n"
            f"عدد الحزم: {d.get('pack',1)}"
        )

    elif q.data == "packs":
        pack_num = data[str(user.id)]["pack"]
        text = ""
        bot = (await context.bot.get_me()).username
        for i in range(1,pack_num+1):
            text += f"https://t.me/addstickers/pack_{user.id}_{i}_by_{bot}\n"
        await q.edit_message_text(text or "ماكو حزم")

# ================== DELETE ==================
async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ حذف الستيكر يتم من داخل تيليجرام حالياً")

# ================== RENAME ==================
async def rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✏️ تغيير الاسم حالياً يدوي من @Stickers")

# ================== MAIN ==================
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("rename", rename))

    app.add_handler(MessageHandler(filters.ALL, handle))
    app.add_handler(CallbackQueryHandler(buttons))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    print("VIP BOT RUNNING 🔥")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
