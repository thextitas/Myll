from dotenv import load_dotenv
import os

load_dotenv()  # this loads variables from .env into os.environ

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

import os
import sqlite3
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

import json
import os
import random

VIDEOS_FILE = "videos.json"

def load_videos():
    if not os.path.exists(VIDEOS_FILE):
        return []
    with open(VIDEOS_FILE, "r") as f:
        return json.load(f)

def save_videos(videos):
    with open(VIDEOS_FILE, "w") as f:
        json.dump(videos, f)


def add_video(file_id):
    videos = load_videos()
    if file_id not in videos:
        videos.append(file_id)
        save_videos(videos)

def get_random_video():
    videos = load_videos()
    if videos:
        return random.choice(videos)
    return None
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# --- DB setup ---
conn = sqlite3.connect("/mnt/data/coins.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY,
  coins INTEGER DEFAULT 0,
  referred_by INTEGER,
  created_at TEXT
);
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS referrals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  referrer_id INTEGER,
  referred_id INTEGER,
  rewarded INTEGER DEFAULT 0,
  created_at TEXT
);
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  type TEXT,
  amount INTEGER,
  meta TEXT,
  created_at TEXT
);
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS videos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id TEXT,
  cost INTEGER DEFAULT 2,
  title TEXT
);
""")
conn.commit()

# --- Helper functions ---
def ensure_user(user_id, referred_by=None):
    cur.execute("INSERT OR IGNORE INTO users (user_id, coins, referred_by, created_at) VALUES (?, ?, ?, ?)",
                (user_id, 0, referred_by, datetime.utcnow().isoformat()))
    conn.commit()

def get_coins(user_id):
    cur.execute("SELECT coins FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0

def add_coins(user_id, amount, meta=None):
    ensure_user(user_id)
    cur.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (amount, user_id))
    cur.execute("INSERT INTO transactions (user_id, type, amount, meta, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, "credit", amount, meta or "", datetime.utcnow().isoformat()))
    conn.commit()

def deduct_coins(user_id, amount, meta=None):
    if get_coins(user_id) < amount:
        return False
    cur.execute("UPDATE users SET coins = coins - ? WHERE user_id=?", (amount, user_id))
    cur.execute("INSERT INTO transactions (user_id, type, amount, meta, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, "debit", amount, meta or "", datetime.utcnow().isoformat()))
    conn.commit()
    return True

def already_referred(referred_id):
    cur.execute("SELECT 1 FROM referrals WHERE referred_id=?", (referred_id,))
    return cur.fetchone() is not None

def save_referral(referrer_id, referred_id):
    cur.execute("INSERT INTO referrals (referrer_id, referred_id, rewarded, created_at) VALUES (?, ?, ?, ?)",
                (referrer_id, referred_id, 1, datetime.utcnow().isoformat()))
    conn.commit()

async def save_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = update.message.video.file_id
    cost = 2  # default cost (can change if you want)
    # Avoid duplicates
    cur.execute("SELECT 1 FROM videos WHERE file_id = ?", (file_id,))
    if cur.fetchone():
        await update.message.reply_text("⚠️ This video is already saved.")
        return

    cur.execute("INSERT INTO videos (file_id, cost) VALUES (?, ?)", (file_id, cost))
    conn.commit()
    await update.message.reply_text("✅ Video saved!")

async def get_random_video(context):  # Added 'async' and 'context' parameter
    """Only returns videos that pass Telegram's validation"""
    cur.execute("SELECT file_id, cost FROM videos ORDER BY RANDOM()")
    for row in cur.fetchall():
        file_id, cost = row
        try:
            # Quick validation check
            file_info = await context.bot.get_file(file_id)
            if file_info.file_size > 0:  # Basic validity check
                return (file_id, cost)
        except Exception as e:
            print(f"Removing invalid video {file_id}: {e}")
            cur.execute("DELETE FROM videos WHERE file_id=?", (file_id,))
            conn.commit()
            continue
    return None  # No valid videos found
# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    args = context.args
    referrer = None

    # 📢 First message with your TG Channel link
    await update.message.reply_text(
        "📢 TG Channel: https://t.me/BackupBush\n"
        "⚠️ Discord(better option): https://discord.gg/uVnRHHec\n"
        "⚠️ There you can find the bot after blocking\n"
        "⚠️ **ANY PURCHASE WILL ALLOW YOU TO SAVE OR FORWARD VIDEOS**"
    )

    # Check if user exists in DB
    cur.execute("SELECT coins, created_at FROM users WHERE user_id=?", (user_id,))
    user_data = cur.fetchone()
    
    is_new_user = not user_data
    
    # Handle new users (first-time starters)
    if is_new_user:
        # Give 10 free coins to new users
        cur.execute("""
            INSERT INTO users (user_id, coins, created_at) 
            VALUES (?, ?, ?)
            """, (user_id, 10, datetime.utcnow().isoformat()))
        welcome_text = "🎉 Welcome! You received 10 free coins!"
    else:
        welcome_text = "Welcome back!"
    

    if args:
        try:
            referrer = int(args[0])
        except ValueError:
            referrer = None
    # Ensure current user exists in DB (to avoid missing users)
    ensure_user(user_id)

    # Handle referral only if not already referred, referrer is valid and not the user themselves
    if not already_referred(user_id) and referrer and referrer != user_id:
        ensure_user(referrer)  # Make sure referrer exists in DB
        add_coins(referrer, 10, meta=f"referral:{user_id}")  # Give 10 coins for referral
        save_referral(referrer, user_id)  # Save referral info

        # Save referred_by field in user record
        cur.execute("INSERT OR IGNORE INTO users (user_id, coins, referred_by, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, 0, referrer, datetime.utcnow().isoformat()))
        cur.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referrer, user_id))
        conn.commit()
    else:
        ensure_user(user_id)

    keyboard = [
        [InlineKeyboardButton("🎥 Get Video (2 coins)", callback_data="get_video")],
        [InlineKeyboardButton("💰 My Coins", callback_data="check_coins")],
        [InlineKeyboardButton("🎁 Daily Bonus (10 coins)", callback_data="daily_bonus")],
        [InlineKeyboardButton("👥 Referral Link", callback_data="referral")]
    ]
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=InlineKeyboardMarkup(keyboard))

from datetime import datetime, timedelta

# Helper function to get last daily bonus claim time
def get_last_daily_claim(user_id):
    cur.execute(
        "SELECT created_at FROM transactions WHERE user_id=? AND meta='daily_bonus' ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    if row:
        return datetime.fromisoformat(row[0])
    return None

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    back_keyboard = [
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")]
    ]

    if data == "check_coins":
        # Show submenu with Check Balance and Daily Bonus buttons
        keyboard = [
            [InlineKeyboardButton("💰 Check Balance", callback_data="check_balance")],
            [InlineKeyboardButton("💳 Top Up", callback_data="top_up")],
        ] + back_keyboard
        await query.edit_message_text("Choose an option:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "check_balance":
        coins = get_coins(user_id)
        await query.edit_message_text(
            f"You have {coins} coins 💰",
            reply_markup=InlineKeyboardMarkup(back_keyboard) 
 
        )
    elif data == "top_up":
        top_up_text = (
        "⚠️ ANY PURCHASE WILL ALLOW YOU TO SAVE OR FORWARD VIDEOS\n\n"
        "💰 Top Up Coins - Payment Methods 💰\n\n"
        "   - 100 coins = $3 (🔥 +10% bonus)\n"
        "   - 250 coins = $5 (🎁 +20% bonus)\n"
        "   - 500 coins = $9 (💎 +30% bonus)\n"
        "   - Unlimited coins for 1 week = $20\n"
        "   - MEGA PACK (2000+ videos) = $30 (⚡ +50% bonus)\n\n"
        "🔹 **Option 1 - Pay with Crypto**\n"
        "• **BTC (Additional +10% bonus for every crypto payment)**:\n"
        "• **BTC (Bitcoin Network)**:\n"
        "  `bc1q5ay582m7q0zwk943d38rzewjxr4av4z6fg5cfj`\n"
        "• **ETH/USDT-ERC20 (Ethereum Network)**:\n"
        "  `0x82992a0B2e959A7b361924CD1b631ee4B46EA01F`\n"
        "• **XRP (XRP Ledger)**:\n"
        "  Address: `rapsDdXZ5hzq6bLumPXUkhjqDfSq3cB3UL`\n"
        "  *MEMO/TAG: REQUIRED if sending from exchanges*\n\n"
        "📌 **After Payment:**\n"
        "1. Send:\n"
        "   - (press on the contact tab)\n"
        "   - Screenshot of payment\n"
        "   - TX ID (for crypto)\n"
        "   - Selected package (e.g., '500 coins')\n"
        "2. Wait 5-30 mins for manual approval\n\n"
        "⚠️ **Critical Rules:**\n"
        "• **USDT must be sent as ERC-20 ONLY**\n"
        "• **XRP requires MEMO/TAG** (or funds will be lost)\n"
        "• No refunds for wrong-network deposits\n"
        "• BTC/XRP/ETH must be sent to their exact networks\n"
        "🔹 **Option 2 - Buy Vouchers via Eneba or other places just make sure you can accept the code in european region**\n"
        "Choose from the buttons below."
        "📌 **Choose the wanted ammount from the links**\n"
        "1. Send me the code from your voucher (press on the contact tab)\n"
        "2. Wait 5-30 mins for manual approval\n\n"
        "⚠️ **No refunds for invalid or already used codes**"
        )  
        voucher_keyboard = [
            [InlineKeyboardButton("💳 Buy Crypto Voucher", url="https://www.eneba.com/crypto-voucher-crypto-voucher-5-eur-key-global")],
            [InlineKeyboardButton("💳 Buy Steam Voucher", url="https://www.eneba.com/steam-gift-card-steam-wallet-gift-card-5-eur-steam-key-europe")],
            [InlineKeyboardButton("📩Contact Support", url="https://t.me/Nickbush")],  # <-- new button
            [InlineKeyboardButton("⬅️ Back", callback_data="check_coins")]
        ] + back_keyboard
        await query.edit_message_text(
            top_up_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(voucher_keyboard)

        )
    elif data == "daily_bonus":
        last_claim = get_last_daily_claim(user_id)
        now = datetime.utcnow()
        if last_claim is None or now - last_claim > timedelta(days=1):
            add_coins(user_id, 10, meta="daily_bonus")
            text = "You claimed your daily bonus of 10 coins! 🎉"
        else:
            text = "You have already claimed your daily bonus today. Try again tomorrow."
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(back_keyboard)
        )
    elif data == "main_menu":
        keyboard = [
            [InlineKeyboardButton("🎥 Get Another Video (2 coins)", callback_data="get_video")],
            [InlineKeyboardButton("💰 My Coins", callback_data="check_coins")],
            [InlineKeyboardButton("🎁 Daily Bonus (10 coins)", callback_data="daily_bonus")],
            [InlineKeyboardButton("👥 Referral Link", callback_data="referral")]
        ]
        await query.edit_message_text("Welcome back! Choose an option:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "referral":
        link = f"https://t.me/{(await context.bot.get_me()).username}?start={user_id}"
        await query.edit_message_text(
            f"Share this link and earn coins (each referal - 10 coins): {link}",
            reply_markup=InlineKeyboardMarkup(back_keyboard)
        )
    elif data == "get_video":
        video = await get_random_video(context)
        if not video:
            await query.edit_message_text("No video is configured. Admin must /setvideo first.")
            return
    
        file_id, cost = video
        current_coins = get_coins(user_id)
    
        if current_coins < cost:
            # For no coins - ALWAYS send as NEW text message
            await context.bot.send_message(
                chat_id=user_id,
                text="⛔ You need 2 coins to view videos\n"
                 f"Your balance: {current_coins} coins\n\n"
                 "Please top up to continue:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Top Up Coins", callback_data="top_up")],
                    [InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")]
                ])
            )
            await query.answer()
            return
    
        # If has coins - send video with buttons
        deduct_coins(user_id, cost, meta="video_purchase")
        keyboard = [
            [InlineKeyboardButton("🎥 Get Another Video (2 coins)", callback_data="get_video")],
            [InlineKeyboardButton("💳 Top Up", callback_data="top_up")],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")]
        ]

        # List of user IDs who are allowed to download
        allowed_users = [8172637443, 5041626933, 5229178575, 6858542775, 7216731920, 8194528857, 5130502442, 8495319504 ]  # add the Telegram IDs of buyers here
        # FIRST send the video
        await context.bot.send_video(
            chat_id=user_id,
            video=file_id,
            caption=f"Remaining coins: {current_coins - cost}",
            protect_content=(user_id not in allowed_users)  # only protect if NOT allowed
        )
        
        # THEN send the buttons as a SEPARATE text message
        await context.bot.send_message(
            chat_id=user_id,
            text="What would you like to do next?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
        await query.answer()
        

# Admin: reply to a video message with /setvideo to save file_id
async def setvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Unauthorized.")
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.video:
        await update.message.reply_text("Reply to a video with this command.")
        return
    file_id = update.message.reply_to_message.video.file_id
    cur.execute("INSERT INTO videos (file_id, cost, title) VALUES (?, ?, ?)", (file_id, 2, "Default video"))
    conn.commit()
    await update.message.reply_text("Saved video file_id and set cost to 2 coins.")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    coins = get_coins(user_id)
    await update.message.reply_text(f"You have {coins} coins.")

# Admin add coins: /addcoins <user_id> <amount>
async def addcoins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Unauthorized.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addcoins <user_id> <amount>")
        return
    target = int(context.args[0]); amount = int(context.args[1])
    add_coins(target, amount, meta=f"admin_added:{update.effective_user.id}")
    await update.message.reply_text(f"Added {amount} coins to {target}.")
# Command function
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Unauthorized.")
        return
    conn = sqlite3.connect("/mnt/data/coins.db")  # replace with your database file
    cur = conn.cursor()

    # Get total users
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]

    # # Get total referrals (number of rows in referrals table)
    cur.execute("SELECT COUNT(*)  FROM referrals")
    total_referrals = cur.fetchone()[0] or 0

    conn.close()

    await update.message.reply_text(
        f"Total users: {total_users}\nTotal referrals: {total_referrals}"
    )


# --- App setup ---

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("setvideo", setvideo))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("addcoins", addcoins_cmd))
    app.add_handler(MessageHandler(filters.VIDEO, save_video))
    print("Bot started (polling)...")
    app.run_polling()

if __name__ == "__main__":
    main()
