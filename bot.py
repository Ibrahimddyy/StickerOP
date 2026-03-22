import os
from PIL import Image
# حل مشكلة ANTIALIAS عبر التوافق مع النسخ الجديدة والقديمة
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import VideoFileClip
from telegram import Update, ReplyKeyboardMarkup, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
user_data = {}

def main_kb():
    return ReplyKeyboardMarkup([["📸 تحويل صورة", "🎥 تحويل فيديو"], ["📦 إنشاء حزمة جديدة"]], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 أرسل 'إنشاء حزمة' للبدء!", reply_markup=main_kb())

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = await update.message.reply_text("⏳ جاري المعالجة...")
    try:
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            await file.download_to_drive("stk.png")
            img = Image.open("stk.png").convert("RGBA")
            img.thumbnail((512, 512), Image.ANTIALIAS)
            img.save("out.webp", "WEBP")
        elif update.message.video:
            file = await update.message.video.get_file()
            await file.download_to_drive("vid.mp4")
            clip = VideoFileClip("vid.mp4").subclip(0, 2.9)
            clip.resize(height=512).write_videofile("out.webm", codec="libvpx-vp9", audio=False)
            clip.close()
        
        with open("out.webp" if update.message.photo else "out.webm", "rb") as f:
            await context.bot.send_sticker(chat_id=user_id, sticker=f)
        await msg.delete()
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    app.run_polling()
    
