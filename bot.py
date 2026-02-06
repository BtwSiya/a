import asyncio
import logging
import re
import random
from pyrogram import Client, filters, idle
from pyrogram.errors import (
    FloodWait, RPCError, UserAlreadyParticipant, 
    MessageNotModified, ChatWriteForbidden, PeerIdInvalid
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8572528424:AAErREWZ0rxRYnzyJw06dRgOsrwQRcEhlkc"
SESSION_STRING = "BQFGCokAgeUYbfqZyyM_tUlZOL9e4XM-eNqZX7_433fLwjvGB4SKL2YC6GBy-7S8ySKF4mwvaFE3FoUPQBrptI68vigVx7RBBwcUlV8LjHDK7CDuyin3nF8vIusS6g3ujLgQBBKajb7IhGPQVOMm-9q2kdROazENzXx-BHPVr3XaSeLM3gtPnY1T_y_RukGosNOfHTfwMkD0oS7fj0zl6KNwO4OgQEAFzTXmfpw9cAW9hCItiT16Q9UE9E75IhekfoPxCSVgwYt35fN7FCPzz8hQNIQwSLikifoeb5XAYSBGHwOnwIdiiovPwLZ9cB9tbEE4utODrHCqZLgVNhcTcjRcVod2MwAAAAF5efmpAA"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot Client
app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Userbot Client (In Memory to prevent database locks)
userbot = Client(
    "userbot_session", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    session_string=SESSION_STRING,
    in_memory=True
)

# Global Storage
BATCH_TASKS = {}
USER_STATE = {}

# ================= UTILS =================

async def force_join(link_or_username):
    """Tries to join the chat automatically."""
    try:
        if "t.me/+" in link_or_username or "joinchat" in link_or_username:
            await userbot.join_chat(link_or_username)
            return True
        elif "t.me/" in link_or_username and "t.me/c/" not in link_or_username:
            # Public username join
            username = link_or_username.split("t.me/")[-1].split("/")[0]
            await userbot.join_chat(username)
            return True
    except UserAlreadyParticipant:
        return True
    except Exception as e:
        logger.warning(f"Auto-Join Failed for {link_or_username}: {e}")
        return False

async def resolve_chat(link_or_id: str):
    """Resolves chat ID and Auto-Joins if necessary."""
    link_or_id = str(link_or_id).strip()
    
    # Clean ID from link if present (e.g., t.me/c/1234/55 -> t.me/c/1234)
    if "/" in link_or_id and link_or_id.split("/")[-1].isdigit():
        parts = link_or_id.split("/")
        # Keep base link for joining logic, but we need ID for pyrogram
        # We will re-process this later
        pass

    try:
        # CASE 1: Numeric ID
        if re.match(r"^-?\d+$", link_or_id):
            return int(link_or_id)
        
        # CASE 2: Private Channel Link (t.me/c/...)
        if "t.me/c/" in link_or_id:
            # Must be joined already or it will fail, private links act as IDs
            chat_id = int("-100" + link_or_id.split("t.me/c/")[1].split("/")[0])
            return chat_id

        # CASE 3: Join Links / Public Usernames -> AUTO JOIN HERE
        await force_join(link_or_id)
        
        # Get Chat Object
        if "t.me/" in link_or_id:
            # Extract username or join link processing
            if "joinchat" in link_or_id or "+" in link_or_id:
                 # If we joined successfully above, get_chat works with invite link sometimes
                 # or we need to find the chat in dialogs (complex). 
                 # Simplest: Userbot joins, then we rely on cached peer.
                 chat = await userbot.get_chat(link_or_id)
                 return chat.id
            else:
                username = link_or_id.split("t.me/")[-1].split("/")[0]
                chat = await userbot.get_chat(username)
                return chat.id
                
    except Exception as e:
        logger.error(f"Resolve Error: {e}")
        return None
    return None

def get_link_msg_id(link: str):
    """Extracts Message ID from link."""
    if "/" in link and link.split("/")[-1].isdigit():
        return int(link.split("/")[-1])
    return None

# ================= ENGINE =================

async def update_log(task_id):
    task = BATCH_TASKS.get(task_id)
    if not task: return
    try:
        status_text = "🟢 **Running**" if task['running'] else "🔴 **Stopped**"
        log_text = (
            f"📊 **Live Task Report: {task_id}**\n\n"
            f"🆔 **Source:** `{task['source']}`\n"
            f"🎯 **Dest:** `{task['dest']}`\n"
            f"🔢 **Processing Msg:** `{task['current']}`\n"
            f"✅ **Copied:** `{task['total']}`\n"
            f"⏭️ **Skipped:** `{task['skipped']}`\n\n"
            f"⏳ *Status: {status_text}*"
        )
        await app.edit_message_text(
            task['user_id'], task['log_msg_id'], log_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 Stop {task_id}", callback_data=f"kill_{task_id}")]])
        )
    except: pass

async def run_batch_worker(task_id):
    consecutive_errors = 0
    
    while task_id in BATCH_TASKS and BATCH_TASKS[task_id]['running']:
        task = BATCH_TASKS[task_id]
        
        try:
            # 1. GET MESSAGE
            try:
                msg = await userbot.get_messages(task['source'], task['current'])
            except RPCError:
                msg = None

            # 2. CHECK IF EMPTY/DELETED
            if not msg or msg.empty:
                task['skipped'] += 1
                task['current'] += 1
                consecutive_errors += 1
                if consecutive_errors > 20: await asyncio.sleep(5)
                continue 

            consecutive_errors = 0 # Reset error count if msg found
            
            # 3. COPY MESSAGE
            if not msg.service:
                try:
                    await userbot.copy_message(task['dest'], task['source'], msg.id)
                    task['total'] += 1
                    if task['total'] % 5 == 0: await update_log(task_id)
                    await asyncio.sleep(3) # Safe Delay
                    
                except ChatWriteForbidden:
                    # Critical Error: Bot cannot write to destination
                    logger.error(f"Write Forbidden in {task['dest']}. Trying to join...")
                    # Try to join purely based on ID is hard, usually handled in setup.
                    # We just skip this message to avoid infinite loop
                    task['skipped'] += 1
                    
                except FloodWait as e:
                    logger.warning(f"Sleeping {e.value}s")
                    await asyncio.sleep(e.value + 5)
                    
                except RPCError as e:
                    logger.error(f"Copy Fail {msg.id}: {e}")
                    task['skipped'] += 1
            
            task['current'] += 1
            
        except Exception as e:
            logger.error(f"Worker Loop Error: {e}")
            await asyncio.sleep(5)

# ================= HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    USER_STATE[message.from_user.id] = None
    await message.reply_text(
        "🚀 **Pro Media Forwarder (Auto-Join Fixed)**\nSelect option:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Start Task", callback_data="new_batch")],
            [InlineKeyboardButton("📊 Status", callback_data="view_status")]
        ])
    )

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    uid = query.from_user.id
    data = query.data
    if data == "new_batch":
        USER_STATE[uid] = {"step": "SOURCE"}
        await query.message.edit_text("🔗 **Step 1:** Send Source Channel Link.")
    elif data == "view_status":
        active_btns = []
        for tid, t_info in BATCH_TASKS.items():
            if t_info['running'] and t_info['user_id'] == uid:
                active_btns.append([InlineKeyboardButton(f"🛑 Stop {tid}", callback_data=f"kill_{tid}")])
        if not active_btns: await query.answer("No active tasks.", show_alert=True)
        else: await query.message.edit_text("Active Tasks:", reply_markup=InlineKeyboardMarkup(active_btns))
    elif data.startswith("kill_"):
        tid = int(data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.answer("Stopped!")
            del BATCH_TASKS[tid]

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE or not USER_STATE[uid]: return
    step = USER_STATE[uid]["step"]
    
    # --- SOURCE STEP ---
    if step == "SOURCE":
        status_msg = await message.reply("⏳ **Joining/Checking Source...**")
        src = await resolve_chat(message.text)
        
        if src:
            USER_STATE[uid]["source_id"] = src
            start_id = get_link_msg_id(message.text)
            
            if start_id:
                USER_STATE[uid]["start_id"] = start_id
                USER_STATE[uid]["step"] = "DEST"
                await status_msg.edit(f"✅ Source Connected!\nStart ID: `{start_id}`\n\n🔗 **Step 2:** Send Destination Link/ID.")
            else:
                USER_STATE[uid]["step"] = "ASK_ID"
                await status_msg.edit("✅ Source Connected!\n🔢 **Now send the Start Message ID** (e.g. 2).")
        else: 
            await status_msg.edit("❌ **Cannot Access Source.**\nEnsure Userbot is joined or link is correct.")

    # --- ASK ID STEP ---
    elif step == "ASK_ID":
        try:
            USER_STATE[uid]["start_id"] = int(message.text)
            USER_STATE[uid]["step"] = "DEST"
            await message.reply("✅ ID Saved. Now send **Destination Link**.")
        except: 
            await message.reply("❌ Send a number only.")

    # --- DESTINATION STEP ---
    elif step == "DEST":
        status_msg = await message.reply("⏳ **Joining/Checking Destination...**")
        dest = await resolve_chat(message.text)
        
        if dest:
            tid = random.randint(1000, 9999)
            
            BATCH_TASKS[tid] = {
                "source": USER_STATE[uid]["source_id"],
                "dest": dest,
                "current": USER_STATE[uid]["start_id"],
                "total": 0, "skipped": 0, "running": True,
                "user_id": uid, "log_msg_id": status_msg.id
            }
            
            await status_msg.edit(f"🚀 **Task {tid} Started!**\nAuto-Joined Chats ✅\nForwarding from ID: {USER_STATE[uid]['start_id']}")
            USER_STATE[uid] = None
            asyncio.create_task(run_batch_worker(tid))
        else: 
            await status_msg.edit("❌ **Destination Error!**\nBot failed to join/find destination.\nMake sure the link is correct.")

# ================= BOOT =================

async def main():
    print("--- Starting Bots ---")
    await app.start()
    await userbot.start()
    print("--- System Ready ---")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
                    
