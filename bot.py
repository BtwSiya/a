import asyncio
import logging
import re
import random
import os
import sys
import time
from pyrogram import Client, filters, idle
from pyrogram.errors import (
    FloodWait, RPCError, UserAlreadyParticipant, 
    MessageNotModified, ChatWriteForbidden, ChatAdminRequired,
    ChatForwardsRestricted, InviteHashExpired, UsernameNotOccupied
)
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, 
    InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio
)

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8572528424:AAG3Bk4L-xnpmu2IWMfRS_m5AG8foG7cPRc"
SESSION_STRING = "BQFGCokAgeUYbfqZyyM_tUlZOL9e4XM-eNqZX7_433fLwjvGB4SKL2YC6GBy-7S8ySKF4mwvaFE3FoUPQBrptI68vigVx7RBBwcUlV8LjHDK7CDuyin3nF8vIusS6g3ujLgQBBKajb7IhGPQVOMm-9q2kdROazENzXx-BHPVr3XaSeLM3gtPnY1T_y_RukGosNOfHTfwMkD0oS7fj0zl6KNwO4OgQEAFzTXmfpw9cAW9hCItiT16Q9UE9E75IhekfoPxCSVgwYt35fN7FCPzz8hQNIQwSLikifoeb5XAYSBGHwOnwIdiiovPwLZ9cB9tbEE4utODrHCqZLgVNhcTcjRcVod2MwAAAAF5efmpAA"

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Clients
app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, in_memory=True)

# Database/Storage
BATCH_TASKS = {}
USER_STATE = {}
PROCESSED_ALBUMS = [] 

# ================= UTILS & HELPERS =================

async def resolve_chat(link_or_id: str):
    """Deep resolution for all Telegram link types"""
    link_or_id = str(link_or_id).strip().rstrip("/")
    
    # 1. Numeric ID
    if re.match(r"^-?\d+$", link_or_id): 
        return int(link_or_id)
    
    # 2. Private Link (/c/ format)
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            chat_id = int("-100" + parts[parts.index('c') + 1])
            return chat_id
        except Exception as e:
            logger.error(f"Private link resolution failed: {e}")
            return None

    # 3. Invite Links (+ or joinchat)
    if "+" in link_or_id or "joinchat" in link_or_id:
        try:
            try:
                await userbot.join_chat(link_or_id)
            except UserAlreadyParticipant:
                pass
            chat_info = await userbot.get_chat(link_or_id)
            return chat_info.id
        except Exception as e:
            logger.error(f"Invite join failed: {e}")
            return None

    # 4. Public Usernames
    try:
        username = link_or_id.split('/')[-1]
        try:
            await userbot.join_chat(username)
        except:
            pass
        chat = await userbot.get_chat(username)
        return chat.id
    except Exception as e:
        logger.error(f"Username resolution failed: {e}")
        return None

async def get_thumb(msg):
    """Downloads thumbnail to prevent black screen on restricted content"""
    if not msg: return None
    try:
        if msg.video and msg.video.thumbs:
            return await userbot.download_media(msg.video.thumbs[0].file_id)
        if msg.document and msg.document.thumbs:
            return await userbot.download_media(msg.document.thumbs[0].file_id)
    except Exception as e:
        logger.debug(f"Thumb download error: {e}")
    return None

# ================= LIVE REPORTING =================

async def update_live_report(task_id, activity="Running"):
    t = BATCH_TASKS.get(task_id)
    if not t: return
    
    status = "🟢 Running" if t['running'] else "🛑 Stopped"
    text = (
        f"📊 **Live Task Report: {task_id}**\n\n"
        f"✅ **Success:** `{t['total']}`\n"
        f"❌ **Failed:** `{t['failed']}`\n"
        f"⏭️ **Skipped:** `{t['skipped']}`\n"
        f"📍 **Current ID:** `{t['current']}`\n\n"
        f"⚡ **Activity:** `{activity}`\n"
        f"📢 **Status:** {status}\n"
        f"⚠️ **Last Error:** `{t['last_error']}`"
    )
    
    try:
        await app.edit_message_text(
            t['user_id'], t['log_msg_id'], text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🛑 Stop Task {task_id}", callback_data=f"kill_{task_id}")]
            ])
        )
    except Exception:
        pass

# ================= CORE WORKER =================

async def run_batch_worker(task_id):
    while task_id in BATCH_TASKS and BATCH_TASKS[task_id]['running']:
        t = BATCH_TASKS[task_id]
        try:
            # 1. Fetch Message
            msg = await userbot.get_messages(t['source'], t['current'])
            
            # LIVE MONITORING LOGIC
            if not msg or msg.empty:
                try:
                    history = await userbot.get_history(t['source'], limit=1)
                    if history and t['current'] > history[0].id:
                        await update_live_report(task_id, "👀 Waiting for new messages...")
                        await asyncio.sleep(15) # Wait for new content
                        continue
                    else:
                        t['skipped'] += 1
                        t['current'] += 1
                        continue
                except Exception:
                    t['current'] += 1
                    continue

            if msg.service:
                t['current'] += 1
                continue

            # 2. ALBUM HANDLING (Grouping Fix)
            if msg.media_group_id:
                if msg.media_group_id in PROCESSED_ALBUMS:
                    t['current'] += 1
                    continue
                
                await update_live_report(task_id, "📥 Processing Album...")
                try:
                    album_messages = await userbot.get_media_group(t['source'], msg.id)
                    PROCESSED_ALBUMS.append(msg.media_group_id)
                    if len(PROCESSED_ALBUMS) > 200: PROCESSED_ALBUMS.pop(0)
                    
                    last_id_in_album = max([m.id for m in album_messages])
                    
                    try:
                        # Attempt Fast Copy
                        await userbot.copy_media_group(t['dest'], t['source'], msg.id)
                        t['total'] += len(album_messages)
                    except ChatForwardsRestricted:
                        # Restricted Content Bypass
                        await update_live_report(task_id, f"📥 Downloading Album ({len(album_messages)})...")
                        media_group = []
                        temp_files = []
                        
                        for m in album_messages:
                            file_path = await userbot.download_media(m)
                            temp_files.append(file_path)
                            thumb_path = await get_thumb(m)
                            if thumb_path: temp_files.append(thumb_path)
                            
                            cap = m.caption or ""
                            if m.photo:
                                media_group.append(InputMediaPhoto(file_path, caption=cap))
                            elif m.video:
                                media_group.append(InputMediaVideo(
                                    file_path, caption=cap, thumb=thumb_path,
                                    width=m.video.width, height=m.video.height, 
                                    duration=m.video.duration, supports_streaming=True
                                ))
                            elif m.document:
                                media_group.append(InputMediaDocument(file_path, caption=cap, thumb=thumb_path))
                            elif m.audio:
                                media_group.append(InputMediaAudio(file_path, caption=cap, thumb=thumb_path, duration=m.audio.duration))

                        if media_group:
                            await update_live_report(task_id, "📤 Uploading Album Group...")
                            await userbot.send_media_group(t['dest'], media=media_group)
                            t['total'] += len(media_group)
                        
                        # Clean up
                        for f in temp_files:
                            if f and os.path.exists(f): os.remove(f)

                    t['current'] = last_id_in_album + 1
                    continue
                except Exception as e:
                    t['failed'] += 1
                    t['last_error'] = f"Album: {str(e)[:50]}"
                    t['current'] += 1
                    continue

            # 3. SINGLE MESSAGE HANDLING
            else:
                try:
                    # Text Message Support
                    if msg.text:
                        await userbot.send_message(t['dest'], msg.text, entities=msg.entities)
                        t['total'] += 1
                    else:
                        # Media Support
                        try:
                            await userbot.copy_message(t['dest'], t['source'], msg.id)
                        except ChatForwardsRestricted:
                            await update_live_report(task_id, "📥 Downloading Restricted File...")
                            path = await userbot.download_media(msg)
                            thumb = await get_thumb(msg)
                            cap = msg.caption or ""
                            
                            if msg.photo:
                                await userbot.send_photo(t['dest'], path, caption=cap)
                            elif msg.video:
                                await userbot.send_video(
                                    t['dest'], path, caption=cap, thumb=thumb,
                                    duration=msg.video.duration, width=msg.video.width,
                                    height=msg.video.height, supports_streaming=True
                                )
                            elif msg.document:
                                await userbot.send_document(t['dest'], path, caption=cap, thumb=thumb)
                            elif msg.audio:
                                await userbot.send_audio(t['dest'], path, caption=cap, thumb=thumb, duration=msg.audio.duration)
                            elif msg.voice:
                                await userbot.send_voice(t['dest'], path, caption=cap)
                            
                            if path and os.path.exists(path): os.remove(path)
                            if thumb and os.path.exists(thumb): os.remove(thumb)
                        
                        t['total'] += 1
                        
                except Exception as e:
                    t['failed'] += 1
                    t['last_error'] = str(e)[:50]

            t['current'] += 1
            await update_live_report(task_id, "⏳ Forwarding...")
            await asyncio.sleep(2.5) # Anti-Flood Delay

        except FloodWait as e:
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            t['last_error'] = f"Main: {str(e)[:50]}"
            await asyncio.sleep(5)

# ================= UI HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    text = (
        "🚀 **Advanced Media Forwarder Pro**\n\n"
        "✅ **Full Album Grouping:** Sends media together\n"
        "✅ **Live Monitor:** Auto-forwards new messages\n"
        "✅ **Join Bypass:** Supports Private Invite Links\n"
        "✅ **Quality Fix:** Metadata & Thumbnails preserved"
    )
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Start Forwarding", callback_data="new_batch")],
        [InlineKeyboardButton("📊 Active Tasks", callback_data="view_status")]
    ])
    await message.reply_text(text, reply_markup=btns)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    uid, data = query.from_user.id, query.data
    
    if data == "new_batch":
        USER_STATE[uid] = {"step": "SOURCE"}
        await query.message.edit_text("🔗 **Step 1: Source Link**\nSend the link of the channel/group you want to copy from.\n_(Supports t.me/+, t.me/c/, etc.)_")
    
    elif data == "view_status":
        active_btns = [
            [InlineKeyboardButton(f"🛑 Stop Task {tid}", callback_data=f"kill_{tid}")] 
            for tid, t in BATCH_TASKS.items() if t['running'] and t['user_id'] == uid
        ]
        if not active_btns:
            return await query.answer("No active tasks found!", show_alert=True)
        await query.message.edit_text("📋 **Current Running Tasks:**", reply_markup=InlineKeyboardMarkup(active_btns))
    
    elif data.startswith("kill_"):
        tid = int(data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.message.edit_text(f"✅ **Task {tid} has been stopped.**")

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE: return
    
    step = USER_STATE[uid]["step"]
    
    if step == "SOURCE":
        status_msg = await message.reply("🔍 **Resolving Source Link...**")
        
        user_input = message.text.strip()
        start_id = 1
        link_to_check = user_input
        
        # Check for start ID in link
        if re.search(r"/\d+$", user_input):
            try:
                parts = user_input.rsplit('/', 1)
                start_id = int(parts[1])
                link_to_check = parts[0]
            except: pass
            
        source_id = await resolve_chat(link_to_check)
        if not source_id:
            return await status_msg.edit("❌ **Invalid Source!**\nMake sure the link is correct and the userbot can access it.")
        
        USER_STATE[uid].update({"source": source_id, "start": start_id, "step": "DEST"})
        await status_msg.edit(f"✅ **Source Resolved!**\n🆔 ID: `{source_id}`\n📍 Start ID: `{start_id}`\n\n📥 **Step 2: Destination Link**\nSend the link where you want to forward messages.")

    elif step == "DEST":
        status_msg = await message.reply("🔍 **Resolving Destination Link...**")
        
        dest_id = await resolve_chat(message.text)
        if not dest_id:
            return await status_msg.edit("❌ **Invalid Destination!**\nMake sure the userbot is a member of the destination.")
        
        task_id = random.randint(10000, 99999)
        BATCH_TASKS[task_id] = {
            "source": USER_STATE[uid]['source'],
            "dest": dest_id,
            "current": USER_STATE[uid]['start'],
            "total": 0, "failed": 0, "skipped": 0,
            "running": True, "user_id": uid,
            "log_msg_id": status_msg.id,
            "last_error": "None"
        }
        
        del USER_STATE[uid]
        await status_msg.edit(f"🚀 **Task {task_id} Initialized!**\nForwarding has started...")
        asyncio.create_task(run_batch_worker(task_id))

# ================= EXECUTION =================

async def main():
    await app.start()
    await userbot.start()
    logger.info("Bot & Userbot are online!")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
                                                                   
