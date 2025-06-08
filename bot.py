import sqlite3
import random
import string
import time
import asyncio
from telegram import Update, InputMediaDocument, InputMediaPhoto, InputMediaVideo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

# Database Setup
conn = sqlite3.connect("files.db", check_same_thread=False)
cursor = conn.cursor()

def column_exists(table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    for column in columns:
        if column[1] == column_name:
            return True
    return False

# Add this right after your database connection setup
conn = sqlite3.connect("files.db", check_same_thread=False)
cursor = conn.cursor()

def column_exists(table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    return any(col[1] == column_name for col in columns)

def migrate_database():
    # Migrate files table
    if not column_exists('files', 'delete_time'):
        cursor.execute("ALTER TABLE files ADD COLUMN delete_time INTEGER")
    if not column_exists('files', 'auto_delete'):
        cursor.execute("ALTER TABLE files ADD COLUMN auto_delete INTEGER DEFAULT 0")
    if not column_exists('files', 'delete_after_hours'):
        cursor.execute("ALTER TABLE files ADD COLUMN delete_after_hours INTEGER DEFAULT 24")
    
    # Create global_config table if not exists
    cursor.execute("""CREATE TABLE IF NOT EXISTS global_config (
        id INTEGER PRIMARY KEY,
        default_auto_delete INTEGER DEFAULT 0,
        default_delete_after_hours INTEGER DEFAULT 24
    )""")
    
    # Initialize global config with default values if empty
    cursor.execute("INSERT OR IGNORE INTO global_config (id) VALUES (1)")
    conn.commit()

# Run migrations before any other operations
migrate_database()

# The rest of your existing code follows...
# Initialize database tables
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT)")
cursor.execute("""CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    file_id TEXT,
    code TEXT,
    user_id INTEGER,
    file_type TEXT,
    caption TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    delete_time INTEGER,
    auto_delete INTEGER DEFAULT 0,
    delete_after_hours INTEGER DEFAULT 24
)""")
cursor.execute("CREATE TABLE IF NOT EXISTS temp_files (user_id INTEGER, file_id TEXT, file_type TEXT, caption TEXT)")
cursor.execute("""CREATE TABLE IF NOT EXISTS global_config (
    id INTEGER PRIMARY KEY,
    default_auto_delete INTEGER DEFAULT 0,
    default_delete_after_hours INTEGER DEFAULT 24
)""")
# Initialize global config if not exists
cursor.execute("INSERT OR IGNORE INTO global_config (id) VALUES (1)")
conn.commit()

# Replace with your actual user ID and your friends' user IDs
AUTHORIZED_USERS = {
    5647525608,  # Your user ID
    1764307921,  # Friend 1
    2025395515,  # Friend 2
    7238049840,
    286469410   # Friend 3
}

START_TIME = time.time()

def get_uptime():
    seconds = int(time.time() - START_TIME)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h {minutes}m {seconds}s"

def generate_code():
    return "".join(random.choices(string.ascii_letters + string.digits, k=8))

def is_authorized(user_id):
    return user_id in AUTHORIZED_USERS

def get_global_config():
    cursor.execute("SELECT default_auto_delete, default_delete_after_hours FROM global_config WHERE id=1")
    return cursor.fetchone()

def update_global_config(auto_delete=None, delete_after_hours=None):
    updates = []
    params = []
    
    if auto_delete is not None:
        updates.append("default_auto_delete = ?")
        params.append(auto_delete)
    if delete_after_hours is not None:
        updates.append("default_delete_after_hours = ?")
        params.append(delete_after_hours)
    
    if updates:
        query = "UPDATE global_config SET " + ", ".join(updates) + " WHERE id=1"
        cursor.execute(query, params)
        conn.commit()

def get_code_config(code):
    cursor.execute("SELECT auto_delete, delete_after_hours FROM files WHERE code=? LIMIT 1", (code,))
    return cursor.fetchone()

def update_code_config(code, auto_delete=None, delete_after_hours=None):
    updates = []
    params = []
    
    if auto_delete is not None:
        updates.append("auto_delete = ?")
        params.append(auto_delete)
    if delete_after_hours is not None:
        updates.append("delete_after_hours = ?")
        params.append(delete_after_hours)
    
    if updates:
        query = "UPDATE files SET " + ", ".join(updates) + " WHERE code=?"
        params.append(code)
        cursor.execute(query, params)
        conn.commit()

async def file_handler(update: Update, context: CallbackContext):
    if not is_authorized(update.message.from_user.id):
        await update.message.reply_text("🚫 You are not authorized to upload files.")
        return

    file = None
    file_type = ""
    caption = update.message.caption
    user_id = update.message.from_user.id

    if 'file_batch_count' not in context.user_data:
        context.user_data['file_batch_count'] = 0
        context.user_data['last_notification'] = 0

    # Debug logging - safe forwarding check
    is_forwarded = hasattr(update.message, 'forward_origin')
    print(f"New message received - Is forwarded: {is_forwarded}")

    if update.message.document:
        file = update.message.document
        file_type = "document"
    elif update.message.photo:
        file = update.message.photo[-1]
        file_type = "photo"
    elif update.message.audio:
        file = update.message.audio
        file_type = "audio"
    elif update.message.video:
        file = update.message.video
        file_type = "video"
    elif update.message.voice:
        file = update.message.voice
        file_type = "voice"
    elif update.message.video_note:
        file = update.message.video_note
        file_type = "video_note"
    elif update.message.animation:
        file = update.message.animation
        file_type = "animation"
    elif update.message.sticker:
        file = update.message.sticker
        file_type = "sticker"
    else:
        return

    file_id = file.file_id
    print(f"Processing {file_type} file - ID: {file_id}")

    try:
        # Skip download verification if the message is forwarded (using the correct attribute)
        if not is_forwarded:
            print("Not a forwarded message - attempting download...")
            file_obj = await context.bot.get_file(file_id)
            await file_obj.download_to_drive()
            print("Download successful")
        else:
            print("Forwarded message - skipping download verification")
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        await update.message.reply_text("⚠️ Error: This file appears to be invalid or inaccessible. Please resend it.")
        return

    cursor.execute(
        "INSERT INTO temp_files (user_id, file_id, file_type, caption) VALUES (?, ?, ?, ?)",
        (user_id, file_id, file_type, caption)
    )
    conn.commit()
    
    context.user_data['file_batch_count'] += 1
    cursor.execute("SELECT COUNT(*) FROM temp_files WHERE user_id=?", (user_id,))
    total_files = cursor.fetchone()[0]

    if total_files < 10:
        await update.message.reply_text("📥 Files received. Use /savefiles when done.")
    else:
        await update.message.reply_text(f"📥 Received {total_files} files in this batch. Use /savefiles when ready.")

async def save_files(update: Update, context: CallbackContext):
    if not is_authorized(update.message.from_user.id):
        await update.message.reply_text("🚫 You are not authorized to save files.")
        return

    user_id = update.message.from_user.id
    code = generate_code()
    total_saved = 0
    
    default_auto_delete, default_delete_after = get_global_config()
    delete_time = None
    if default_auto_delete:
        delete_time = time.time() + (default_delete_after * 3600)
    
    cursor.execute("SELECT file_id, file_type, caption FROM temp_files WHERE user_id=?", (user_id,))
    files = cursor.fetchall()
    
    if not files:
        await update.message.reply_text("📭 No files found! Please upload files first.")
        return

    for file_entry in files:
        file_id, file_type, caption = file_entry
        cursor.execute(
            "INSERT INTO files (file_id, code, user_id, file_type, caption, delete_time, auto_delete, delete_after_hours) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, code, user_id, file_type, caption, delete_time, default_auto_delete, default_delete_after)
        )
        total_saved += 1
    
    cursor.execute("DELETE FROM temp_files WHERE user_id=?", (user_id,))
    conn.commit()
    
    if 'file_batch_count' in context.user_data:
        context.user_data['file_batch_count'] = 0
        context.user_data['last_notification'] = 0

    deep_link = f"https://t.me/{context.bot.username}?start={code}"
    
    auto_delete_info = ""
    if default_auto_delete:
        auto_delete_info = f"\n⏳ Files will auto-delete after {default_delete_after} hours."

    response = (
        f"💾 Successfully saved {total_saved} files!\n"
        f"🔗 Share link: <code>{deep_link}</code>\n"
        f"🆔 Code: <code>{code}</code>"
        f"{auto_delete_info}"
    )
    
    await update.message.reply_text(response, parse_mode='HTML')

async def start(update: Update, context: CallbackContext):
    user = update.message.from_user
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (user.id, user.username)
    )
    conn.commit()

    if context.args:
        code = context.args[0]
        cursor.execute("SELECT file_id, file_type, caption FROM files WHERE code=?", (code,))
        results = cursor.fetchall()

        if not results:
            await update.message.reply_text("🔍 Invalid or expired link.")
            return

        media_groups = []
        current_group = []
        current_group_type = None
        groupable_types = {'photo', 'video', 'document', 'audio'}

        for file_entry in results:
            file_id, file_type, caption = file_entry

            if file_type in groupable_types:
                if file_type == current_group_type and len(current_group) < 10:
                    current_group.append((file_type, file_id, caption))
                else:
                    if current_group:
                        media_groups.append(current_group)
                    current_group = [(file_type, file_id, caption)]
                    current_group_type = file_type
            else:
                if current_group:
                    media_groups.append(current_group)
                    current_group = []
                    current_group_type = None
                media_groups.append([(file_type, file_id, caption)])

        if current_group:
            media_groups.append(current_group)

        max_retries = 3
        for group in media_groups:
            for attempt in range(max_retries):
                try:
                    if len(group) > 1:
                        media = []
                        for idx, (ftype, fid, cap) in enumerate(group):
                            if ftype == 'photo':
                                media.append(InputMediaPhoto(fid, caption=cap if idx == 0 else None))
                            elif ftype == 'video':
                                media.append(InputMediaVideo(fid, caption=cap if idx == 0 else None))
                            elif ftype == 'document':
                                media.append(InputMediaDocument(fid, caption=cap if idx == 0 else None))
                            elif ftype == 'audio':
                                media.append(InputMediaDocument(fid, caption=cap if idx == 0 else None))
                        
                        await update.message.reply_media_group(media=media, write_timeout=30)
                    else:
                        ftype, fid, cap = group[0]
                        send_methods = {
                            'photo': update.message.reply_photo,
                            'audio': update.message.reply_audio,
                            'video': update.message.reply_video,
                            'voice': update.message.reply_voice,
                            'video_note': update.message.reply_video_note,
                            'animation': update.message.reply_animation,
                            'sticker': update.message.reply_sticker
                        }
                        method = send_methods.get(ftype, update.message.reply_document)
                        await method(fid, caption=cap, write_timeout=20)
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"Retrying {attempt + 1}/{max_retries} - Error: {str(e)}")
                        await asyncio.sleep(2)
                    else:
                        await update.message.reply_text(f"⌛ Failed to send files after multiple attempts. Error: {str(e)}")
                        continue
    else:
        await update.message.reply_text(
            "🌟 Welcome to the File Sharing Bot! 🌟\n\n"
            "📤 To upload files:\n"
            "1. Send me any files (photos, videos, documents, etc.)\n"
            "2. Use /savefiles when done to get a shareable link\n\n"
            "📥 To download files:\n"
            "• Click on any shared link from this bot\n\n"
            "🔧 Other commands:\n"
            "/viewfiles - See your uploaded files\n"
            "/deletefiles [code] - Delete a file batch\n"
            "/cancelupload - Cancel current upload session\n"
            "/config - Configure auto-delete settings\n\n"
            "🚀 Start by sending me some files!",
            parse_mode='HTML'
        )

async def help_command(update: Update, context: CallbackContext):
    help_text = """
<b>📚 Bot Command Guide</b>

<b>👋 General Commands:</b>
/start - Welcome message and instructions
/help - Show this help message

<b>📤 Upload Commands:</b>
/savefiles - Save uploaded files and generate link
/cancelupload - Cancel current upload session

<b>🗂 File Management:</b>
/viewfiles - View your uploaded files with codes
/deletefiles [code] - Delete files using their code

<b>⚙️ Configuration:</b>
/config - Configure auto-delete settings
/config [code] - Configure specific file batch

<b>⚙️ Admin Tools:</b>
/stats - View bot statistics
/broadcast - Send message to all users
/uptime - Show bot running time

<b>🔄 How to Use:</b>
1. Send files (photos, videos, documents etc)
2. Use /savefiles to get shareable link
3. Share the link with anyone
"""

    if is_authorized(update.message.from_user.id):
        await update.message.reply_text(help_text, parse_mode='HTML')
    else:
        basic_help = """
<b>📚 Available Commands:</b>
/start - Welcome message
/help - Show this help

<b>🔄 How to Use:</b>
• Click shared links to download files
• Contact owner for upload access
"""
        await update.message.reply_text(basic_help, parse_mode='HTML')

async def delete_files(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("🚫 You are not authorized to delete files.")
        return

    if not context.args:
        await update.message.reply_text("ℹ Usage: /deletefiles <code>")
        return
    
    code = context.args[0]
    
    cursor.execute("SELECT COUNT(*) FROM files WHERE code=? AND user_id=?", (code, user_id))
    count = cursor.fetchone()[0]
    if count == 0:
        await update.message.reply_text("❌ Either the code is invalid or you don't own these files.")
        return
    
    cursor.execute("DELETE FROM files WHERE code=? AND user_id=?", (code, user_id))
    conn.commit()
    await update.message.reply_text("🗑️ Files successfully deleted!")

async def view_files(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("🚫 You are not authorized to view files.")
        return

    cursor.execute("""
        SELECT code, caption, file_type, COUNT(*) as file_count, auto_delete, delete_after_hours
        FROM files 
        WHERE user_id=?
        GROUP BY code
        ORDER BY MAX(timestamp) DESC
        LIMIT 50
    """, (user_id,))
    results = cursor.fetchall()
    
    if not results:
        await update.message.reply_text("📭 Your file vault is empty!")
        return

    type_emojis = {
        'video': '🎬',
        'document': '📄',
        'photo': '🖼️',
        'audio': '🎵',
        'voice': '🎤',
        'animation': '🎞️',
        'sticker': '🩹'
    }

    response = "✨ <b>Your File Vault</b> ✨\n\n"
    for code, caption, file_type, file_count, auto_delete, delete_after in results:
        emoji = type_emojis.get(file_type, '📁')
        filename = (caption.split('\n')[0][:50] + '...') if caption else f"Unnamed {file_type}"
        
        auto_delete_info = "🔴 OFF" if not auto_delete else f"🟢 ON ({delete_after}h)"
        
        response += (
            f"{emoji} <b>{filename}</b>\n"
            f"   📂 Files: <code>{file_count}</code>\n"
            f"   🕒 Auto-delete: {auto_delete_info}\n"
            f"   🔗 <code>https://t.me/{context.bot.username}?start={code}</code>\n"
            f"   🆔 <code>{code}</code>\n\n"
        )

    total_files = sum(row[3] for row in results)
    total_links = len(results)
    response += f"📊 <i>Showing {total_links} most recent batches ({total_files} files total)</i>"

    await update.message.reply_text(
        response, 
        parse_mode='HTML',
        disable_web_page_preview=True
    )

async def stats(update: Update, context: CallbackContext):
    if not is_authorized(update.message.from_user.id):
        await update.message.reply_text("🚫 You are not authorized to view statistics.")
        return

    cursor.execute("SELECT COUNT(*) FROM files")
    total_files = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT code) FROM files")
    total_links = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    response = (
        f"📈 <b>Bot Statistics</b>\n\n"
        f"• 📦 Total Files: <code>{total_files}</code>\n"
        f"• 🔗 Total Share Links: <code>{total_links}</code>\n"
        f"• 👥 Total Users: <code>{total_users}</code>\n"
        f"• ⏱ Uptime: <code>{get_uptime()}</code>"
    )
    await update.message.reply_text(response, parse_mode='HTML')

async def cancel_upload(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id

    if not is_authorized(user_id):
        await update.message.reply_text("🚫 You are not authorized to cancel uploads.")
        return

    cursor.execute("DELETE FROM temp_files WHERE user_id=?", (user_id,))
    conn.commit()

    if 'file_batch_count' in context.user_data:
        context.user_data['file_batch_count'] = 0
        context.user_data['last_notification'] = 0

    await update.message.reply_text("❌ Your pending file uploads have been canceled.")

async def broadcast(update: Update, context: CallbackContext):
    if not is_authorized(update.message.from_user.id):
        await update.message.reply_text("🚫 You are not authorized to broadcast messages.")
        return

    if update.message.text == '/broadcast_confirm':
        if 'pending_broadcast' not in context.user_data:
            await update.message.reply_text("⚠️ No pending broadcast to confirm.")
            return
            
        original_msg = await context.bot.get_message(
            chat_id=update.message.chat_id,
            message_id=context.user_data['pending_broadcast']
        )
        users = cursor.execute("SELECT user_id FROM users").fetchall()
        await start_broadcast_task(update, context, original_msg, users)
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "ℹ How to broadcast:\n\n"
            "1. Send the content you want to broadcast (text, photo, video, etc.)\n"
            "2. Reply to that message with /broadcast\n\n"
            "The bot will forward your exact message to all users."
        )
        return

    users = cursor.execute("SELECT user_id FROM users").fetchall()
    original_msg = update.message.reply_to_message

    if len(users) > 50:
        context.user_data['pending_broadcast'] = original_msg.message_id
        await update.message.reply_text(
            f"⚠️ This will broadcast to {len(users)} users. "
            f"Confirm with /broadcast_confirm or cancel by ignoring."
        )
        return

    await start_broadcast_task(update, context, original_msg, users)

async def start_broadcast_task(update: Update, context: CallbackContext, original_msg, users):
    progress_msg = await update.message.reply_text(
        "📢 Starting broadcast...\n"
        "⏳ Progress: 0%\n"
        "✅ Success: 0\n"
        "❌ Failed: 0"
    )

    success = 0
    failed = 0
    total_users = len(users)
    start_time = time.time()

    for index, (user_id,) in enumerate(users):
        try:
            if index > 0 and index % 25 == 0:
                await asyncio.sleep(1)

            if index % 10 == 0 or index == total_users - 1:
                progress = int((index + 1) / total_users * 100)
                await context.bot.edit_message_text(
                    chat_id=progress_msg.chat_id,
                    message_id=progress_msg.message_id,
                    text=(
                        f"📢 Broadcasting...\n"
                        f"⏳ Progress: {progress}%\n"
                        f"✅ Success: {success}\n"
                        f"❌ Failed: {failed}\n"
                        f"⏱ Elapsed: {int(time.time() - start_time)}s"
                    )
                )

            if original_msg.text:
                await context.bot.send_message(chat_id=user_id, text=original_msg.text)
            elif original_msg.photo:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=original_msg.photo[-1].file_id,
                    caption=original_msg.caption
                )
            elif original_msg.video:
                await context.bot.send_video(
                    chat_id=user_id,
                    video=original_msg.video.file_id,
                    caption=original_msg.caption
                )
            elif original_msg.document:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=original_msg.document.file_id,
                    caption=original_msg.caption
                )
            elif original_msg.audio:
                await context.bot.send_audio(
                    chat_id=user_id,
                    audio=original_msg.audio.file_id,
                    caption=original_msg.caption
                )
            elif original_msg.voice:
                await context.bot.send_voice(chat_id=user_id, voice=original_msg.voice.file_id)
            elif original_msg.animation:
                await context.bot.send_animation(
                    chat_id=user_id,
                    animation=original_msg.animation.file_id,
                    caption=original_msg.caption
                )
            else:
                failed += 1
                continue
                
            success += 1
        except Exception as e:
            print(f"Failed to send to {user_id}: {e}")
            failed += 1
            continue

    elapsed_time = int(time.time() - start_time)
    await context.bot.edit_message_text(
        chat_id=progress_msg.chat_id,
        message_id=progress_msg.message_id,
        text=(
            f"📢 <b>Broadcast Complete</b>\n\n"
            f"✅ Success: <code>{success}</code>\n"
            f"❌ Failed: <code>{failed}</code>\n"
            f"📊 Total Users: <code>{total_users}</code>\n"
            f"⏱ Elapsed Time: <code>{elapsed_time}s</code>\n\n"
            f"{(success/total_users*100):.1f}% delivery success rate"
        ),
        parse_mode='HTML'
    )

    if 'pending_broadcast' in context.user_data:
        del context.user_data['pending_broadcast']

async def uptime(update: Update, context: CallbackContext):
    if not is_authorized(update.message.from_user.id):
        await update.message.reply_text("🚫 You are not authorized to view uptime.")
        return
    await update.message.reply_text(f"⏱ <b>Bot Uptime:</b> <code>{get_uptime()}</code>", parse_mode='HTML')

async def config_command(update: Update, context: CallbackContext):
    if not is_authorized(update.message.from_user.id):
        await update.message.reply_text("🚫 You are not authorized to configure settings.")
        return

    user_id = update.message.from_user.id
    
    # Check if configuring a specific code
    if context.args:
        code = context.args[0]
        cursor.execute("SELECT COUNT(*) FROM files WHERE code=? AND user_id=?", (code, user_id))
        if cursor.fetchone()[0] == 0:
            await update.message.reply_text("❌ Invalid code or you don't own these files.")
            return
        
        config = get_code_config(code)
        if not config:
            config = get_global_config()
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔄 Auto-delete: {'ON' if config[0] else 'OFF'}",
                    callback_data=f"code_toggle_{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    f"⏱ Delete after: {config[1]} hours",
                    callback_data=f"code_set_time_{code}"
                )
            ],
            [InlineKeyboardButton("❌ Close", callback_data="config_close")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"⚙️ <b>Configuration for code: {code}</b>\n\n"
            "Configure auto-delete settings for this specific file batch:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return
    
    # Global configuration
    config = get_global_config()
    
    keyboard = [
        [
            InlineKeyboardButton(
                f"🔄 Default Auto-delete: {'ON' if config[0] else 'OFF'}",
                callback_data="global_toggle"
            )
        ],
        [
            InlineKeyboardButton(
                f"⏱ Default Delete after: {config[1]} hours",
                callback_data="global_set_time"
            )
        ],
        [InlineKeyboardButton("❌ Close", callback_data="config_close")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚙️ <b>Global Configuration Settings</b>\n\n"
        "Configure default auto-delete settings for new files:",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def config_button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not is_authorized(user_id):
        await query.edit_message_text("🚫 You are not authorized to configure settings.")
        return

    data = query.data
    
    if data == "config_close":
        await query.delete_message()
        return
        
    elif data.startswith("code_toggle_"):
        code = data[12:]
        current_setting, hours = get_code_config(code)
        new_setting = not current_setting
        
        # Only update if there's a change
        if new_setting != current_setting:
            update_code_config(code, auto_delete=int(new_setting))
            config = (new_setting, hours)
        else:
            config = (current_setting, hours)
        
        # Rebuild keyboard with updated values
        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔄 Auto-delete: {'ON' if config[0] else 'OFF'}",
                    callback_data=f"code_toggle_{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    f"⏱ Delete after: {config[1]} hours",
                    callback_data=f"code_set_time_{code}"
                )
            ],
            [InlineKeyboardButton("❌ Close", callback_data="config_close")]
        ]
        
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except BadRequest:
            # Ignore "message not modified" error
            pass
        return
        
    elif data.startswith("code_set_time_"):
        code = data[14:]
        await query.edit_message_text(
            f"⏳ <b>Set auto-delete time for code: {code}</b>\n\n"
            "Send the number of hours after which these files should be automatically deleted (1-720):",
            parse_mode='HTML'
        )
        context.user_data['awaiting_code_time'] = code
        context.user_data['config_message_id'] = query.message.message_id
        return
        
    elif data == "global_toggle":
        current_setting, hours = get_global_config()
        new_setting = not current_setting
        
        # Only update if there's a change
        if new_setting != current_setting:
            update_global_config(auto_delete=int(new_setting))
            config = (new_setting, hours)
        else:
            config = (current_setting, hours)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔄 Default Auto-delete: {'ON' if config[0] else 'OFF'}",
                    callback_data="global_toggle"
                )
            ],
            [
                InlineKeyboardButton(
                    f"⏱ Default Delete after: {config[1]} hours",
                    callback_data="global_set_time"
                )
            ],
            [InlineKeyboardButton("❌ Close", callback_data="config_close")]
        ]
        
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except BadRequest:
            # Ignore "message not modified" error
            pass
        return
        
    elif data == "global_set_time":
        await query.edit_message_text(
            "⏳ <b>Set default auto-delete time</b>\n\n"
            "Send the number of hours after which new files should be automatically deleted (1-720):",
            parse_mode='HTML'
        )
        context.user_data['awaiting_global_time'] = True
        context.user_data['config_message_id'] = query.message.message_id
        return

async def handle_config_text(update: Update, context: CallbackContext):
    if 'awaiting_global_time' in context.user_data:
        try:
            hours = int(update.message.text)
            if not 1 <= hours <= 720:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ Please enter a valid number between 1 and 720.")
            return

        update_global_config(delete_after_hours=hours)
        await update.message.delete()
        
        config_message_id = context.user_data['config_message_id']
        config = get_global_config()
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔄 Default Auto-delete: {'ON' if config[0] else 'OFF'}",
                    callback_data="global_toggle"
                )
            ],
            [
                InlineKeyboardButton(
                    f"⏱ Default Delete after: {config[1]} hours",
                    callback_data="global_set_time"
                )
            ],
            [InlineKeyboardButton("❌ Close", callback_data="config_close")]
        ]

        await context.bot.edit_message_text(
            chat_id=update.message.chat_id,
            message_id=config_message_id,
            text="⚙️ <b>Global Configuration Settings</b>\n\n"
                 "Configure default auto-delete settings for new files:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        
        del context.user_data['awaiting_global_time']
        del context.user_data['config_message_id']
        
    elif 'awaiting_code_time' in context.user_data:
        try:
            hours = int(update.message.text)
            if not 1 <= hours <= 720:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ Please enter a valid number between 1 and 720.")
            return

        code = context.user_data['awaiting_code_time']
        update_code_config(code, delete_after_hours=hours)
        await update.message.delete()
        
        config_message_id = context.user_data['config_message_id']
        config = get_code_config(code)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔄 Auto-delete: {'ON' if config[0] else 'OFF'}",
                    callback_data=f"code_toggle_{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    f"⏱ Delete after: {config[1]} hours",
                    callback_data=f"code_set_time_{code}"
                )
            ],
            [InlineKeyboardButton("❌ Close", callback_data="config_close")]
        ]

        await context.bot.edit_message_text(
            chat_id=update.message.chat_id,
            message_id=config_message_id,
            text=f"⚙️ <b>Configuration for code: {code}</b>\n\n"
                 "Configure auto-delete settings for this specific file batch:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        
        del context.user_data['awaiting_code_time']
        del context.user_data['config_message_id']

async def error_handler(update: Update, context: CallbackContext) -> None:
    """Logs errors and notifies users."""
    print(f"⚠️ Error: {context.error}")  # Log to console
    if update and update.message:
        await update.message.reply_text("❌ Oops! Something went wrong. Try again or notify the admin.")
    # Optional: Notify admin via Telegram
    # await context.bot.send_message(chat_id=ADMIN_ID, text=f"Bot error: {context.error}")

async def check_auto_delete(context: CallbackContext):
    current_time = time.time()
    # Delete expired files directly instead of selecting first
    cursor.execute("""
        DELETE FROM files 
        WHERE auto_delete = 1 
          AND (delete_time <= ? OR (delete_time IS NULL AND (timestamp + (delete_after_hours * 3600)) <= ?))
    """, (current_time, current_time))
    conn.commit()

def main():
    TOKEN = "7620276659:AAGTotFOs42O7bbWmmWQirw4BSrvDoflpOU"
    
    print("💖 Starting bot...")
    app = Application.builder().token(TOKEN)\
        .read_timeout(30)\
        .connect_timeout(30)\
        .pool_timeout(30)\
        .build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("savefiles", save_files))
    app.add_handler(CommandHandler("deletefiles", delete_files))
    app.add_handler(CommandHandler("viewfiles", view_files))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("cancelupload", cancel_upload))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("config", config_command))
    app.add_error_handler(error_handler)  # Place this with your other handlers

    # Callback handlers
    app.add_handler(CallbackQueryHandler(config_button, pattern="^code_|^global_|^config_"))
    
    # Message handlers
    file_filter = (filters.Document.ALL | filters.PHOTO | filters.AUDIO |
                  filters.VIDEO | filters.VOICE | filters.VIDEO_NOTE |
                  filters.ANIMATION | filters.Sticker.ALL)
    app.add_handler(MessageHandler(file_filter, file_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_config_text))

    # Job queue for auto-delete
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(check_auto_delete, interval=300, first=10)

    print("💖 Your bot is ready, my king!")
    app.run_polling(
        poll_interval=3,
        timeout=30,
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
