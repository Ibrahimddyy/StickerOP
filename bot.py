import os
from PIL import Image
from moviepy import VideoFileClip

from telegram import Update, ReplyKeyboardMarkup, InputSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

# سنفصل بيانات الحزم عن البيانات المؤقتة لكي لا تُحذف
user_packs = {} 
temp = {}

# ===== keyboard =====
def keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📸 صورة", "🎥 فيديو"],
            ["📦 انشاء حزمة", "🗂️ حزمي"],
            ["🧠 ايموجي تلقائي", "📊 احصائياتي"]
        ],
        resize_keyboard=True
    )

# ===== start =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 بوت ستيكر احترافي\nاختار من القائمة:",
        reply_markup=keyboard()
    )

# ===== text =====
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    text = update.message.text

    if user_id not in temp: temp[user_id] = {}

    if text == "📸 صورة":
        temp[user_id]["mode"] = "photo"
        await update.message.reply_text("ارسل الصورة")

    elif text == "🎥 فيديو":
        temp[user_id]["mode"] = "video"
        await update.message.reply_text("ارسل الفيديو")

    elif text == "🧠 ايموجي تلقائي":
        temp[user_id]["auto"] = not temp[user_id].get("auto", False)
        status = "تفعيل" if temp[user_id]["auto"] else "تعطيل"
        await update.message.reply_text(f"تم {status} الايموجي التلقائي (🔥)")

    elif text == "📊 احصائياتي":
        await update.message.reply_text(f"بوت الستيكرات يعمل بنجاح!")

    elif text == "📦 انشاء حزمة":
        temp[user_id]["create_pack"] = True
        await update.message.reply_text("ارسل اسم الحزمة (بالانجليزي فقط وبدون فراغات)")

    elif temp[user_id].get("create_pack"):
        # اسم الحزمة في تلغرام يجب ان ينتهي بـ _by_اسم_البوت
        bot_info = await context.bot.get_me()
        clean_name = "".join(e for e in text if e.isalnum())
        pack_id = f"s_{user_id}_{clean_name}_by_{bot_info.username}"
        
        user_packs[user_id] = pack_id
        temp[user_id]["create_pack"] = False
        await update.message.reply_text(f"✅ تم حفظ اسم الحزمة: {text}\nارسل اول ملف الآن.")

    elif text == "🗂️ حزمي":
        pack = user_packs.get(user_id)
        if pack:
            await update.message.reply_text(f"حزمتك الحالية:\nhttps://t.me/addstickers/{pack}")
        else:
            await update.message.reply_text("ما عندك حزمة، اضغط على 'انشاء حزمة' أولاً.")

    elif temp[user_id].get("wait"):
        temp[user_id]["emoji"] = text
        temp[user_id]["wait"] = False
        await process(update, context, user_id)

# ===== photo & video handlers =====
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if temp.get(user_id, {}).get("mode") != "photo": return
    file = await update.message.photo[-1].get_file()
    path = f"{user_id}.jpg"
    await file.download_to_drive(path)
    temp[user_id]["file"] = path
    await check_emoji_and_process(update, context, user_id)

async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if temp.get(user_id, {}).get("mode") != "video": return
    file = await update.message.video.get_file()
    path = f"{user_id}.mp4"
    await file.download_to_drive(path)
    temp[user_id]["file"] = path
    temp[user_id]["video"] = True
    await check_emoji_and_process(update, context, user_id)

async def check_emoji_and_process(update, context, user_id):
    if temp[user_id].get("auto"):
        temp[user_id]["emoji"] = "🔥"
        await process(update, context, user_id)
    else:
        temp[user_id]["wait"] = True
        await update.message.reply_text("ارسل ايموجي للستيكر")

# ===== process =====
async def process(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    data = temp[user_id]
    path = data["file"]
    emoji = data.get("emoji", "😄")
    out = ""

    try:
        if data.get("video"):
            clip = VideoFileClip(path)
            # تحديث MoviePy 2.0: subclip صار subclipped
            duration = min(2.9, clip.duration)
            clip = clip.subclipped(0, duration).resized(height=512)
            out = f"{user_id}.webm"
            clip.write_videofile(out, codec="libvpx-vp9", fps=24, bitrate="500k")
            sticker_format = "video"
        else:
            img = Image.open(path)
            img = img.resize((512, 512))
            out = f"{user_id}.webp"
            img.save(out, "WEBP")
            sticker_format = "static"

        # ارسال الستيكر للمستخدم
        with open(out, "rb") as f:
            await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=f)

        # إضافة للحزمة إذا وجدت
        pack_name = user_packs.get(user_id)
        if pack_name:
            with open(out, "rb") as f:
                sticker_obj = InputSticker(sticker=f, emoji_list=[emoji], format=sticker_format)
                try:
                    await context.bot.add_sticker_to_set(user_id=int(user_id), name=pack_name, sticker=sticker_obj)
                    await update.message.reply_text("✅ تمت إضافته لحزمتك!")
                except Exception:
                    await context.bot.create_new_sticker_set(
                        user_id=int(user_id), name=pack_name, title="My Stickers", 
                        stickers=[sticker_obj], sticker_format=sticker_format
                    )
                    await update.message.reply_text("📦 تم إنشاء الحزمة وإضافة الستيكر الأول!")

    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")
    finally:
        # تنظيف الملفات فقط، لا نمسح الـ temp بالكامل لكي لا يضيع اسم الحزمة
        if os.path.exists(path): os.remove(path)
        if out and os.path.exists(out): os.remove(out)
        temp[user_id].pop("file", None)
        temp[user_id].pop("video", None)
        temp[user_id].pop("wait", None)

# ===== run =====
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
app.add_handler(MessageHandler(filters.VIDEO, video_handler))
app.run_polling()
