import asyncio
import logging
import re
import random
import os
from pyrogram import Client, filters, idle
from pyrogram.errors import (
    FloodWait, RPCError, UserAlreadyParticipant, 
    MessageNotModified, ChatWriteForbidden, ChatAdminRequired,
    ChatForwardsRestricted, InviteHashExpired, UsernameNotOccupied
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8572528424:AAG3Bk4L-xnpmu2IWMfRS_m5AG8foG7cPRc"
SESSION_STRING = "BQFGCokAgeUYbfqZyyM_tUlZOL9e4XM-eNqZX7_433fLwjvGB4SKL2YC6GBy-7S8ySKF4mwvaFE3FoUPQBrptI68vigVx7RBBwcUlV8LjHDK7CDuyin3nF8vIusS6g3ujLgQBBKajb7IhGPQVOMm-9q2kdROazENzXx-BHPVr3XaSeLM3gtPnY1T_y_RukGosNOfHTfwMkD0oS7fj0zl6KNwO4OgQEAFzTXmfpw9cAW9hCItiT16Q9UE9E75IhekfoPxCSVgwYt35fN7FCPzz8hQNIQwSLikifoeb5XAYSBGHwOnwIdiiovPwLZ9cB9tbEE4utODrHCqZLgVNhcTcjRcVod2MwAAAAF5efmpAA"

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, in_memory=True)

BATCH_TASKS = {}
USER_STATE = {}
PROCESSED_ALBUMS = [] 

# ================= SMART UTILS =================

async def resolve_chat(link_or_id: str):
    """Auto-Joins and resolves Chat ID for Private/Public Channels & Groups"""
    link_or_id = str(link_or_id).strip().rstrip("/")
    
    # 1. Direct Numeric ID
    if re.match(r"^-?\d+$", link_or_id): 
        return int(link_or_id)
    
    # 2. Private Link with /c/ (Already joined)
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            chat_id_idx = parts.index('c') + 1
            return int("-100" + parts[chat_id_idx])
        except: pass

    # 3. Invite Links (Auto Join)
    if "+" in link_or_id or "joinchat" in link_or_id:
        try:
            # Try joining
            try:
                chat = await userbot.join_chat(link_or_id)
                return chat.id
            except UserAlreadyParticipant:
                # If already there, fetch info. 
                # Note: We can't fetch by invite link if already joined, need to parse or hope we have it.
                # Usually join_chat returns the chat object even if already joined in recent Pyrogram versions.
                pass
        except Exception as e:
            logger.error(f"Join Error: {e}")
            return None

    # 4. Public Username
    try:
        username = link_or_id.split('/')[-1]
        try: 
            await userbot.join_chat(username)
        except: pass
        chat = await userbot.get_chat(username)
        return chat.id
    except Exception: return None
    
    return None

async def get_thumb(msg):
    """Downloads thumbnail to fix black screen issue"""
    if not msg: return None
    try:
        if msg.photo: return None # Photo IS the thumb
        if msg.video and msg.video.thumbs:
            return await userbot.download_media(msg.video.thumbs[0].file_id)
        if msg.document and msg.document.thumbs:
            return await userbot.download_media(msg.document.thumbs[0].file_id)
    except: pass
    return None

# ================= CORE ENGINE =================

async def update_live_report(task_id, activity):
    t = BATCH_TASKS.get(task_id)
    if not t: return
    
    text = (
        f"📊 **Live Task Report: {task_id}**\n\n"
        f"✅ **Success:** `{t['total']}`\n"
        f"❌ **Failed:** `{t['failed']}`\n"
        f"⏭️ **Skipped:** `{t['skipped']}`\n"
        f"📍 **Current ID:** `{t['current']}`\n\n"
        f"⚡ **Activity:** `{activity}`\n"
        f"📢 **Status:** {'🟢 Running' if t['running'] else '🛑 Stopped'}\n"
        f"⚠️ **Last Error:** `{t['last_error']}`"
    )
    try:
        await app.edit_message_text(
            t['user_id'], t['log_msg_id'], text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 Stop Task {task_id}", callback_data=f"kill_{task_id}")]])
        )
    except: pass

async def run_batch_worker(task_id):
    while task_id in BATCH_TASKS and BATCH_TASKS[task_id]['running']:
        t = BATCH_TASKS[task_id]
        try:
            msg = await userbot.get_messages(t['source'], t['current'])
            
            # Message Empty or Service Msg
            if not msg or msg.empty:
                t['skipped'] += 1
                t['current'] += 1
                continue
            if msg.service:
                t['current'] += 1
                continue

            # ================== ALBUM (GROUP) HANDLING ==================
            if msg.media_group_id:
                if msg.media_group_id in PROCESSED_ALBUMS:
                    t['current'] += 1
                    continue
                
                await update_live_report(task_id, "📥 Detecting Album...")
                
                try:
                    # Get all messages in the group
                    media_group = await userbot.get_media_group(t['source'], msg.id)
                    PROCESSED_ALBUMS.append(msg.media_group_id)
                    if len(PROCESSED_ALBUMS) > 100: PROCESSED_ALBUMS.pop(0) # Keep memory low
                    
                    # Update current ID to the last ID of this album to skip others in loop
                    last_id = max([m.id for m in media_group])
                    
                    # Try Direct Copy (Fastest)
                    try:
                        await userbot.copy_media_group(t['dest'], t['source'], msg.id)
                        t['total'] += len(media_group)
                        t['current'] = last_id + 1
                        continue
                    except ChatForwardsRestricted:
                        pass # Fallback to Download/Upload
                    
                    # Restricted Content Bypass (Download -> Upload)
                    await update_live_report(task_id, f"📥 Downloading Album ({len(media_group)} files)...")
                    
                    input_media_list = []
                    files_to_clean = []
                    
                    for m in media_group:
                        # Download File
                        file_path = await userbot.download_media(m)
                        files_to_clean.append(file_path)
                        
                        # Download Thumb (Crucial for Black Screen Fix)
                        thumb_path = await get_thumb(m)
                        if thumb_path: files_to_clean.append(thumb_path)
                        
                        caption = m.caption or ""
                        
                        if m.photo:
                            input_media_list.append(InputMediaPhoto(file_path, caption=caption))
                        elif m.video:
                            input_media_list.append(
                                InputMediaVideo(
                                    file_path, 
                                    caption=caption,
                                    thumb=thumb_path, 
                                    width=m.video.width, 
                                    height=m.video.height, 
                                    duration=m.video.duration,
                                    supports_streaming=True
                                )
                            )
                        elif m.document:
                             input_media_list.append(InputMediaDocument(file_path, caption=caption, thumb=thumb_path))
                        elif m.audio:
                             input_media_list.append(InputMediaAudio(file_path, caption=caption, thumb=thumb_path, duration=m.audio.duration))

                    if input_media_list:
                        await update_live_report(task_id, "📤 Uploading Album...")
                        await userbot.send_media_group(t['dest'], media=input_media_list)
                        t['total'] += len(media_group)
                    
                    # Cleanup
                    for f in files_to_clean:
                        if f and os.path.exists(f): os.remove(f)
                        
                    t['current'] = last_id + 1
                    continue

                except Exception as e:
                    t['failed'] += 1
                    t['last_error'] = f"Album Fail: {str(e)[:50]}"
                    t['current'] += 1 # Try to move on
                    continue

            # ================== SINGLE MESSAGE HANDLING ==================
            else:
                try:
                    await userbot.copy_message(t['dest'], t['source'], msg.id)
                    t['total'] += 1
                except ChatForwardsRestricted:
                    # RESTRICTED CONTENT BYPASS
                    await update_live_report(task_id, "📥 Downloading File...")
                    
                    try:
                        file_path = await userbot.download_media(msg)
                        thumb_path = await get_thumb(msg)
                        
                        await update_live_report(task_id, "📤 Uploading File...")
                        
                        if msg.photo:
                            await userbot.send_photo(t['dest'], file_path, caption=msg.caption)
                        elif msg.video:
                            # FIX: Passing Metadata to prevent Black Screen
                            await userbot.send_video(
                                t['dest'], 
                                file_path, 
                                caption=msg.caption,
                                thumb=thumb_path,
                                duration=msg.video.duration,
                                width=msg.video.width,
                                height=msg.video.height,
                                supports_streaming=True
                            )
                        elif msg.document:
                             await userbot.send_document(t['dest'], file_path, caption=msg.caption, thumb=thumb_path)
                        elif msg.voice:
                             await userbot.send_voice(t['dest'], file_path, caption=msg.caption)
                        elif msg.audio:
                             await userbot.send_audio(t['dest'], file_path, caption=msg.caption, thumb=thumb_path, duration=msg.audio.duration)
                        else:
                            # Fallback for text/stickers
                             if msg.text: await userbot.send_message(t['dest'], msg.text)
                        
                        # Cleanup
                        if file_path and os.path.exists(file_path): os.remove(file_path)
                        if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
                        
                        t['total'] += 1

                    except Exception as e:
                        t['failed'] += 1
                        t['last_error'] = f"Bypass Fail: {str(e)[:50]}"

            t['current'] += 1
            await update_live_report(task_id, "⏳ Waiting...")
            await asyncio.sleep(2) # Safe delay

        except FloodWait as e:
            await update_live_report(task_id, f"😴 Sleep {e.value}s")
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            t['last_error'] = f"Loop Error: {str(e)[:50]}"
            await asyncio.sleep(5)

# ================= UI HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    text = (
        "🚀 **Pro Media Forwarder **\n\n"
        "✅ **Auto Join:** Private & Public Links\n"
        "✅ **Album Support:** Sends Grouped Media correctly\n"
        "✅ **Black Screen Fix:** Metadata & Thumbnails Preserved\n"
        "✅ **Unlimited Size:** Heavy Files Supported"
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
        await query.message.edit_text("🔗 **Step 1: Source**\nSend Public/Private Link (e.g., `https://t.me/+AbCd123` or `t.me/c/123/100`).")
    elif data == "view_status":
        active_btns = [[InlineKeyboardButton(f"🛑 Stop Task {tid}", callback_data=f"kill_{tid}")] 
                       for tid, t in BATCH_TASKS.items() if t['running'] and t['user_id'] == uid]
        if not active_btns: return await query.answer("No active tasks!", show_alert=True)
        await query.message.edit_text("📋 **Active Monitor:**", reply_markup=InlineKeyboardMarkup(active_btns))
    elif data.startswith("kill_"):
        tid = int(data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.message.edit_text(f"✅ **Task {tid} Stopped.**")

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE: return
    step = USER_STATE[uid]["step"]
    
    if step == "SOURCE":
        msg = await message.reply("🔍 **Joining & Resolving Source...**")
        
        # Extract ID if link has message ID (e.g., t.me/c/123/400)
        user_input = message.text.strip()
        start_id = 1
        link_to_resolve = user_input
        
        if re.search(r"/\d+$", user_input):
            try:
                parts = user_input.rsplit('/', 1)
                if parts[1].isdigit():
                    start_id = int(parts[1])
                    link_to_resolve = parts[0]
            except: pass
            
        source = await resolve_chat(link_to_resolve)
        if not source: return await msg.edit("❌ **Cannot Access Source!**\nMake sure the link is correct or the Bot is banned there.")
        
        USER_STATE[uid] = {"step": "DEST", "source": source, "start": start_id}
        await msg.edit(f"✅ **Source Found!**\nStarting from ID: `{start_id}`\n\n📥 **Step 2:** Send Destination Link.")

    elif step == "DEST":
        msg = await message.reply("🔍 **Resolving Destination...**")
        dest = await resolve_chat(message.text)
        if not dest: return await msg.edit("❌ **Invalid Destination!**")
        
        task_id = random.randint(1000, 9999)
        BATCH_TASKS[task_id] = {
            "source": USER_STATE[uid]['source'], "dest": dest, "current": USER_STATE[uid]['start'],
            "total": 0, "failed": 0, "skipped": 0, "running": True,
            "user_id": uid, "log_msg_id": msg.id, "last_error": "None"
        }
        del USER_STATE[uid]
        await msg.edit(f"🚀 **Task {task_id} Started!**\n_Media Grouping & Anti-Black Screen Enabled_")
        asyncio.create_task(run_batch_worker(task_id))

async def main():
    await app.start()
    await userbot.start()
    print("--- Pro Forwarder V7 Running ---")
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
                        
