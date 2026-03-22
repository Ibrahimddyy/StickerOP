import os
from PIL import Image
from moviepy.editor import VideoFileClip # تأكد من استخدام هذا السطر لـ moviepy 1.0.3

from telegram import Update, ReplyKeyboardMarkup, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# توكن البوت
TOKEN = os.getenv("BOT_TOKEN")

# مخازن البيانات
user_packs = {} 
temp = {}

def keyboard():
    return ReplyKeyboardMarkup(
        [["📸 صورة", "🎥 فيديو"], ["📦 انشاء حزمة", "🗂️ حزمي"], ["🧠 ايموجي تلقائي", "📊 احصائياتي"]],
        resize_keyboard=True
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔥 بوت الستيكرات المطور جاهز!\nاختار من القائمة تحت:", reply_markup=keyboard())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    text = update.message.text
    if user_id not in temp: temp[user_id] = {}

    if text == "📸 صورة":
        temp[user_id]["mode"] = "photo"
        await update.message.reply_text("أرسل الصورة الآن")
    elif text == "🎥 فيديو":
        temp[user_id]["mode"] = "video"
        await update.message.reply_text("أرسل الفيديو الآن (يفضل قصير)")
    elif text == "📦 انشاء حزمة":
        temp[user_id]["create_pack"] = True
        await update.message.reply_text("أرسل اسم الحزمة (بالإنجليزي فقط وبدون فراغات)")
    elif temp[user_id].get("create_pack"):
        bot_info = await context.bot.get_me()
        clean_name = "".join(e for e in text if e.isalnum())
        pack_id = f"v_{user_id}_{clean_name}_by_{bot_info.username}"
        user_packs[user_id] = pack_id
        temp[user_id]["create_pack"] = False
        await update.message.reply_text(f"✅ تم تفعيل الحزمة: {text}\nالآن أي ستيكر تصنعه سيضاف إليها تلقائياً.")
    elif text == "🗂️ حزمي":
        pack = user_packs.get(user_id)
        if pack: await update.message.reply_text(f"رابط حزمتك:\nhttps://t.me/addstickers/{pack}")
        else: await update.message.reply_text("ما عندك حزمة حالياً.")
    elif text == "🧠 ايموجي تلقائي":
        temp[user_id]["auto"] = not temp[user_id].get("auto", False)
        status = "تفعيل 🔥" if temp[user_id]["auto"] else "تعطيل ❌"
        await update.message.reply_text(f"تم {status}")
    elif temp[user_id].get("wait"):
        temp[user_id]["emoji"] = text
        temp[user_id]["wait"] = False
        await process(update, context, user_id)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if temp.get(user_id, {}).get("mode") != "photo": return
    file = await update.message.photo[-1].get_file()
    path = f"{user_id}.jpg"
    await file.download_to_drive(path)
    temp[user_id]["file"] = path
    await ask_emoji(update, context, user_id)

async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if temp.get(user_id, {}).get("mode") != "video": return
    file = await update.message.video.get_file()
    path = f"{user_id}.mp4"
    await file.download_to_drive(path)
    temp[user_id]["file"] = path
    temp[user_id]["video"] = True
    await ask_emoji(update, context, user_id)

async def ask_emoji(update, context, user_id):
    if temp[user_id].get("auto"):
        temp[user_id]["emoji"] = "🔥"
        await process(update, context, user_id)
    else:
        temp[user_id]["wait"] = True
        await update.message.reply_text("أرسل ايموجي للستيكر")

async def process(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    data = temp[user_id]
    path = data["file"]
    emoji = data.get("emoji", "😄")
    out = ""
    try:
        if data.get("video"):
            clip = VideoFileClip(path)
            # ضبط المدة (أهم شي للستيكر)
            clip = clip.subclip(0, min(2.9, clip.duration))
            # ضبط المقاسات بدقة 512
            w, h = clip.size
            clip = clip.resize(width=512) if w > h else clip.resize(height=512)
            
            out = f"{user_id}.webm"
            # الإعدادات الصارمة لترميز تلغرام
            clip.write_videofile(
                out, codec="libvpx-vp9", fps=30, bitrate="300k", 
                audio=False, logger=None, ffmpeg_params=["-pix_fmt", "yuva420p"]
            )
            clip.close()
            sticker_format = "video"
        else:
            img = Image.open(path).convert("RGBA")
            # إضافة خلفية بيضاء حتى لا يظهر الستيكر كأنه "مخفي"
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            img = Image.alpha_composite(bg, img).convert("RGB")
            img = img.resize((512, 512))
            out = f"{user_id}.webp"
            img.save(out, "WEBP")
            sticker_format = "static"

        with open(out, "rb") as f:
            await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=f)

        pack_name = user_packs.get(user_id)
        if pack_name:
            with open(out, "rb") as f:
                sticker_obj = InputSticker(sticker=f, emoji_list=[emoji], format=sticker_format)
                try:
                    await context.bot.add_sticker_to_set(user_id=int(user_id), name=pack_name, sticker=sticker_obj)
                    await update.message.reply_text("✅ تمت الإضافة للحزمة!")
                except:
                    await context.bot.create_new_sticker_set(
                        user_id=int(user_id), name=pack_name, title="My Pack", stickers=[sticker_obj]
                    )
                    await update.message.reply_text("📦 تم إنشاء الحزمة وإضافة الستيكر!")

    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")
    finally:
        if os.path.exists(path): os.remove(path)
        if out and os.path.exists(out): os.remove(out)
        temp[user_id].pop("file", None)
        temp[user_id].pop("video", None)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.VIDEO, video_handler))
    app.run_polling()
    
