import os
import json
from PIL import Image
from moviepy.editor import VideoFileClip

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "data.json"

# ===== تحميل البيانات =====
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

# ===== الكيبورد =====
def keyboard():
    return ReplyKeyboardMarkup([
        ["📸 صورة", "🎥 فيديو"],
        ["🧠 ايموجي تلقائي", "📊 احصائياتي"]
    ], resize_keyboard=True)

# ===== بدء =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 بوت ستيكر احترافي\nاخت
