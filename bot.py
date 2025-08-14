import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import sqlite3
from datetime import datetime, timedelta
import asyncio

# --- CONFIGURATION ---
BOT_TOKEN = "BOT_TOKEN"
ADMIN_IDS = [6860094135, 6586857906, 7868668617]

# Only use @username channels for verification (Telegram doesn't allow bot to check private invite links)
CHANNEL_USERNAMES = [
    "@Xstreambideo",
    "@EditingMotionandaitools",
    "@SASincome18",
    "@legalincomeideas"
]

# All channels to show in join buttons (including private invite links)
REQUIRED_CHANNELS_DISPLAY = [
    "@Xstreambideo",
    "@EditingMotionandaitools",
    "@SASincome18",
    "@legalincomeideas",
    "https://t.me/+0hWwurWwpLoxN2Vl",
    "https://t.me/+_dXDu_I-1JBkZTQ1",
    "https://t.me/+KOU5noBdSNYyOTJl"
]

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        referred_by INTEGER,
        videos_watched INTEGER DEFAULT 0,
        unlimited_until TIMESTAMP,
        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS videos (
        code TEXT PRIMARY KEY,
        file_id TEXT,
        added_by INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
        referrer_id INTEGER,
        referee_id INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS required_channels (
        channel TEXT UNIQUE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
    )''')

    # Insert default channels
    for channel in REQUIRED_CHANNELS_DISPLAY:
        try:
            c.execute("INSERT OR IGNORE INTO required_channels (channel) VALUES (?)", (channel.strip(),))
        except:
            pass

    # Insert admins
    for admin_id in ADMIN_IDS:
        c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (admin_id,))

    conn.commit()
    conn.close()

def is_admin(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def get_user(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0], "first_name": row[1], "referred_by": row[2],
            "videos_watched": row[3], "unlimited_until": row[4]
        }
    return None

def add_user(user_id, first_name, referred_by=None):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    try:
        c.execute('''
            INSERT OR IGNORE INTO users (user_id, first_name, referred_by, videos_watched)
            VALUES (?, ?, ?, 0)
        ''', (user_id, first_name, referred_by))
    except:
        pass

    if referred_by:
        c.execute("SELECT 1 FROM referrals WHERE referrer_id = ? AND referee_id = ?", (referred_by, user_id))
        if not c.fetchone():
            c.execute("INSERT INTO referrals (referrer_id, referee_id) VALUES (?, ?)", (referred_by, user_id))
            c.execute("SELECT unlimited_until FROM users WHERE user_id = ?", (referred_by,))
            current = c.fetchone()[0]
            new_time = datetime.now() + timedelta(hours=12)
            if current:
                new_time = max(new_time, datetime.fromisoformat(current) + timedelta(hours=12))
            c.execute("UPDATE users SET unlimited_until = ? WHERE user_id = ?", (new_time.isoformat(), referred_by))
    conn.commit()
    conn.close()

def has_unlimited_access(user_id):
    user = get_user(user_id)
    if not user or not user["unlimited_until"]:
        return False
    return datetime.now() < datetime.fromisoformat(user["unlimited_until"])

def get_remaining_videos(user_id):
    if has_unlimited_access(user_id):
        return "Unlimited"
    user = get_user(user_id)
    if not user:
        return 5
    return max(0, 5 - user["videos_watched"])

def get_referral_count(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_video(code):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT file_id FROM videos WHERE code = ?", (code,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def add_video(code, file_id, admin_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    try:
        c.execute("INSERT OR REPLACE INTO videos (code, file_id, added_by) VALUES (?, ?, ?)", (code, file_id, admin_id))
        conn.commit()
        return True
    finally:
        conn.close()

def remove_video(code):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("DELETE FROM videos WHERE code = ?", (code,))
    changes = conn.total_changes
    conn.commit()
    conn.close()
    return changes > 0

def increment_videos_watched(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET videos_watched = videos_watched + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# --- PERSISTENT BUTTONS AFTER VERIFY ---
def get_main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 My Referral Link", callback_data="my_referral")],
        [InlineKeyboardButton("📊 My Stats", callback_data="my_stats")]
    ])

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    ref_id = None
    if context.args and context.args[0].isdigit():
        ref_id = int(context.args[0])
    add_user(chat_id, user.first_name, ref_id)

    keyboard = []
    for channel in REQUIRED_CHANNELS_DISPLAY:
        if channel.startswith("https://t.me/+"):
            label = "🔗 Join Private Channel"
        else:
            label = f"Join {channel}"
        url = channel if channel.startswith("https://t.me/") else f"https://t.me/{channel.replace('@', '')}"
        keyboard.append([InlineKeyboardButton(label, url=url)])
    keyboard.append([InlineKeyboardButton("✅ Verify", callback_data="verify")])

    welcome_msg = f"""
👋 Welcome, {user.first_name}!

🎯 Bot Features:

📹 Request videos by sending a secret code (example: 1, 2, promoA)

🎁 Invite friends — each referral = 12 hours unlimited access

📊 Track your usage and referrals in My Stats

🆓 Start with 5 free videos (unless unlimited time is active)

📌 Requirements before using the bot:

1. Join all required channels below.
2. Click ✅ Verify after joining.
"""

    await update.message.reply_text(welcome_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    missing = []
    for channel in CHANNEL_USERNAMES:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                missing.append(channel)
        except Exception as e:
            print(f"Verify error for {channel}: {e}")
            missing.append(channel)

    if missing:
        msg = "❌ You must join:\n" + "\n".join([f"• {ch}" for ch in missing])
        keyboard = [[InlineKeyboardButton(f"Join {ch}", url=f"https://t.me/{ch.replace('@', '')}")] for ch in missing]
        keyboard.append([InlineKeyboardButton("✅ Re-Check", callback_data="verify")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.edit_message_text(
            "✅ Verification Successful! You now have access.",
            reply_markup=get_main_menu_keyboard()
        )

async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    missing = []
    for channel in CHANNEL_USERNAMES:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                missing.append(channel)
        except:
            missing.append(channel)

    if missing:
        msg = "❌ Join first:\n" + "\n".join([f"• {ch}" for ch in missing])
        keyboard = [[InlineKeyboardButton(f"Join {ch}", url=f"https://t.me/{ch.replace('@', '')}")] for ch in missing]
        keyboard.append([InlineKeyboardButton("✅ Verify", callback_data="verify")])
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(
            "✅ You are verified!",
            reply_markup=get_main_menu_keyboard()
        )

# --- NEW: Send User's Referral Link When Button is Clicked ---
async def my_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    referral_link = f"https://t.me/Xvideostream_bot?start={user_id}"
    msg = f"""
📤 **Your Personal Referral Link**

`https://t.me/Xvideostream_bot?start={user_id}`

🔗 Copy and share this link!

Each friend who joins gives you **12 hours of unlimited access**.
"""
    await update.callback_query.message.reply_text(
        msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu_keyboard()
    )

# --- Show Stats ---
async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.callback_query.message.reply_text("Start the bot first.")
        return

    unlimited = "✅ Active" if has_unlimited_access(user_id) else "❌ Inactive"
    remaining = get_remaining_videos(user_id)
    ref_count = get_referral_count(user_id)

    msg = f"""
📊 **Your Stats**

• Videos Watched: {user['videos_watched']}
• Remaining: {remaining}
• Referrals: {ref_count}
• Unlimited Access: {unlimited}
"""
    await update.callback_query.message.reply_text(
        msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu_keyboard()
    )

# --- Handle Callbacks ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "verify":
        await verify_callback(update, context)
    elif query.data == "my_referral":
        await my_referral(update, context)
    elif query.data == "my_stats":
        await my_stats(update, context)

# --- Admin Commands ---
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Access denied.")
        return
    msg = """
👑 **Admin Panel**

✅ /addvideo <code> → Add video
✅ /removevideo <code> → Remove
✅ /listvideos → List
✅ /addchannel <link> → Add
✅ /removechannel <link> → Remove
✅ /listchannels → View
✅ /announce <text> → Broadcast
"""
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def addvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("UsageId: /addvideo <code>\nThen send video.")
        return
    context.user_data['awaiting_video'] = context.args[0]
    await update.message.reply_text(f"✅ Send video for code `{context.args[0]}`")

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if 'awaiting_video' not in context.user_data or not is_admin(user_id):
        return
    code = context.user_data.pop('awaiting_video')
    file_id = update.message.video.file_id
    if add_video(code, file_id, user_id):
        await update.message.reply_text(f"✅ Video added: `{code}`", reply_markup=get_main_menu_keyboard())
    else:
        await update.message.reply_text("❌ Failed.")

async def removevideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("UsageId: /removevideo <code>")
        return
    if remove_video(context.args[0]):
        await update.message.reply_text(f"✅ Removed: `{context.args[0]}`")
    else:
        await update.message.reply_text("❌ Not found.")

async def listvideos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT code, added_by FROM videos")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("📭 No videos.")
        return
    msg = "🎥 Videos:\n\n" + "\n".join([f"`{r[0]}` (by {r[1]})" for r in rows])
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("UsageId: /addchannel <link>")
        return
    channel = context.args[0].strip()
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO required_channels (channel) VALUES (?)", (channel,))
        conn.commit()
        await update.message.reply_text(f"✅ Added: `{channel}`")
    except:
        await update.message.reply_text("❌ DB error.")
    finally:
        conn.close()

async def removechannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("UsageId: /removechannel <link>")
        return
    channel = context.args[0].strip()
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("DELETE FROM required_channels WHERE channel = ?", (channel,))
    if conn.total_changes > 0:
        await update.message.reply_text(f"✅ Removed: `{channel}`")
    else:
        await update.message.reply_text(f"❌ Not found: `{channel}`")
    conn.commit()
    conn.close()

async def listchannels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT channel FROM required_channels")
    channels = [row[0] for row in c.fetchall()]
    conn.close()
    if not channels:
        await update.message.reply_text("📭 No channels.")
        return
    msg = "🔗 Channels:\n" + "\n".join([f"`{ch}`" for ch in channels])
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("UsageId: /announce <text>")
        return
    text = " ".join(context.args)
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()

    sent = 0
    for (uid,) in users:
        try:
            await context.bot.send_message(uid, text)
            sent += 1
        except:
            continue
    await update.message.reply_text(f"📢 Sent to {sent} users.")

# --- Handle Video Requests ---
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text.startswith('/'):
        return

    if not get_user(user_id):
        await start(update, context)
        return

    # Verify only @username channels
    missing = []
    for channel in CHANNEL_USERNAMES:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                missing.append(channel)
        except:
            missing.append(channel)
    if missing:
        await update.message.reply_text("❌ Please verify first with /verify")
        return

    if not has_unlimited_access(user_id):
        user = get_user(user_id)
        if user and user["videos_watched"] >= 5:
            await update.message.reply_text(
                "❌ You've used all 5 free videos. Refer friends for unlimited access!",
                reply_markup=get_main_menu_keyboard()
            )
            return

    file_id = get_video(text)
    if not file_id:
        await update.message.reply_text(
            "❌ Invalid code. Try again.",
            reply_markup=get_main_menu_keyboard()
        )
        return

    await update.message.reply_video(video=file_id)
    increment_videos_watched(user_id)
    await update.message.reply_text("✅ Video delivered!", reply_markup=get_main_menu_keyboard())

# --- MAIN ---
async def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("verify", verify_command))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("addvideo", addvideo))
    app.add_handler(CommandHandler("removevideo", removevideo))
    app.add_handler(CommandHandler("listvideos", listvideos))
    app.add_handler(CommandHandler("addchannel", addchannel))
    app.add_handler(CommandHandler("removechannel", removechannel))
    app.add_handler(CommandHandler("listchannels", listchannels))
    app.add_handler(CommandHandler("announce", announce))

    app.add_handler(MessageHandler(filters.VIDEO & filters.User(user_id=ADMIN_IDS), receive_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("🚀 Bot is running...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Stopped.")
    finally:
        await app.updater.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())