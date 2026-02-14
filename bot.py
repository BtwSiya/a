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
    link_or_id = str(link_or_id).strip().rstrip("/")
    if re.match(r"^-?\d+$", link_or_id): 
        return int(link_or_id)
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            chat_id_idx = parts.index('c') + 1
            return int("-100" + parts[chat_id_idx])
        except: pass
    if "+" in link_or_id or "joinchat" in link_or_id:
        try:
            try: await userbot.join_chat(link_or_id)
            except UserAlreadyParticipant: pass
            chat_info = await userbot.get_chat(link_or_id)
            return chat_info.id
        except Exception as e:
            return None
    try:
        username = link_or_id.split('/')[-1]
        try: await userbot.join_chat(username)
        except: pass
        chat = await userbot.get_chat(username)
        return chat.id
    except Exception: return None

async def get_thumb(msg):
    try:
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
            
            if not msg or msg.empty:
                try:
                    history = await userbot.get_history(t['source'], limit=1)
                    if history and t['current'] > history[0].id:
                        await update_live_report(task_id, "Waiting for new messages...")
                        await asyncio.sleep(10)
                        continue
                    else:
                        t['skipped'] += 1
                        t['current'] += 1
                        continue
                except:
                    t['current'] += 1
                    continue

            if msg.service:
                t['current'] += 1
                continue

            # ALBUM HANDLING
            if msg.media_group_id:
                if msg.media_group_id in PROCESSED_ALBUMS:
                    t['current'] += 1
                    continue
                
                try:
                    media_group = await userbot.get_media_group(t['source'], msg.id)
                    PROCESSED_ALBUMS.append(msg.media_group_id)
                    if len(PROCESSED_ALBUMS) > 100: PROCESSED_ALBUMS.pop(0)
                    last_id = max([m.id for m in media_group])
                    
                    try:
                        await userbot.copy_media_group(t['dest'], t['source'], msg.id)
                        t['total'] += len(media_group)
                    except ChatForwardsRestricted:
                        await update_live_report(task_id, "Processing Album Bypass...")
                        input_media = []
                        temp_files = []
                        for m in media_group:
                            path = await userbot.download_media(m)
                            temp_files.append(path)
                            thumb = await get_thumb(m)
                            if thumb: temp_files.append(thumb)
                            
                            cap = m.caption or ""
                            if m.photo: input_media.append(InputMediaPhoto(path, caption=cap))
                            elif m.video: input_media.append(InputMediaVideo(path, caption=cap, thumb=thumb, width=m.video.width, height=m.video.height, duration=m.video.duration, supports_streaming=True))
                            elif m.document: input_media.append(InputMediaDocument(path, caption=cap, thumb=thumb))
                            elif m.audio: input_media.append(InputMediaAudio(path, caption=cap, thumb=thumb, duration=m.audio.duration))

                        await userbot.send_media_group(t['dest'], media=input_media)
                        t['total'] += len(media_group)
                        for f in temp_files:
                            if f and os.path.exists(f): os.remove(f)

                    t['current'] = last_id + 1
                    continue
                except Exception as e:
                    t['failed'] += 1
                    t['last_error'] = str(e)[:50]
                    t['current'] += 1
                    continue

            # SINGLE MESSAGE
            else:
                try:
                    if msg.text:
                        await userbot.send_message(t['dest'], msg.text, entities=msg.entities)
                    else:
                        try:
                            await userbot.copy_message(t['dest'], t['source'], msg.id)
                        except ChatForwardsRestricted:
                            await update_live_report(task_id, "Processing File Bypass...")
                            path = await userbot.download_media(msg)
                            thumb = await get_thumb(msg)
                            cap = msg.caption or ""
                            
                            if msg.photo: await userbot.send_photo(t['dest'], path, caption=cap)
                            elif msg.video: await userbot.send_video(t['dest'], path, caption=cap, thumb=thumb, duration=msg.video.duration, width=msg.video.width, height=msg.video.height, supports_streaming=True)
                            elif msg.document: await userbot.send_document(t['dest'], path, caption=cap, thumb=thumb)
                            elif msg.audio: await userbot.send_audio(t['dest'], path, caption=cap, thumb=thumb, duration=msg.audio.duration)
                            elif msg.voice: await userbot.send_voice(t['dest'], path, caption=cap)
                            
                            if path and os.path.exists(path): os.remove(path)
                            if thumb and os.path.exists(thumb): os.remove(thumb)
                    t['total'] += 1
                except Exception as e:
                    t['failed'] += 1
                    t['last_error'] = str(e)[:50]

            t['current'] += 1
            await update_live_report(task_id, "Waiting...")
            await asyncio.sleep(2)

        except FloodWait as e:
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            t['last_error'] = str(e)[:50]
            await asyncio.sleep(5)

# ================= UI HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    text = (
        "🚀 **Pro Media Forwarder**\n\n"
        "✅ Live Forwarding Enabled\n"
        "✅ Private & Public Support\n"
        "✅ Album & Text Support\n"
        "✅ Black Screen Fix Active"
    )
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Start Task", callback_data="new_batch")],
        [InlineKeyboardButton("📊 Tasks", callback_data="view_status")]
    ])
    await message.reply_text(text, reply_markup=btns)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    uid, data = query.from_user.id, query.data
    if data == "new_batch":
        USER_STATE[uid] = {"step": "SOURCE"}
        await query.message.edit_text("🔗 **Step 1:**\nSend Source Link.")
    elif data == "view_status":
        btns = [[InlineKeyboardButton(f"🛑 Stop {tid}", callback_data=f"kill_{tid}")] for tid, t in BATCH_TASKS.items() if t['running'] and t['user_id'] == uid]
        if not btns: return await query.answer("No active tasks!")
        await query.message.edit_text("📋 **Active Tasks:**", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("kill_"):
        tid = int(data.split("_")[1])
        if tid in BATCH_TASKS: BATCH_TASKS[tid]['running'] = False
        await query.message.edit_text(f"✅ Task {tid} stopped.")

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE: return
    step = USER_STATE[uid]["step"]
    
    if step == "SOURCE":
        user_input = message.text.strip()
        start_id = 1
        link = user_input
        if re.search(r"/\d+$", user_input):
            parts = user_input.rsplit('/', 1)
            start_id = int(parts[1])
            link = parts[0]
            
        source = await resolve_chat(link)
        if not source: return await message.reply("❌ Invalid Source!")
        USER_STATE[uid] = {"step": "DEST", "source": source, "start": start_id}
        await message.reply("📥 **Step 2:**\nSend Destination Link.")

    elif step == "DEST":
        dest = await resolve_chat(message.text)
        if not dest: return await message.reply("❌ Invalid Destination!")
        task_id = random.randint(1000, 9999)
        msg = await message.reply("🚀 Initializing...")
        BATCH_TASKS[task_id] = {
            "source": USER_STATE[uid]['source'], "dest": dest, "current": USER_STATE[uid]['start'],
            "total": 0, "failed": 0, "skipped": 0, "running": True,
            "user_id": uid, "log_msg_id": msg.id, "last_error": "None"
        }
        del USER_STATE[uid]
        asyncio.create_task(run_batch_worker(task_id))

async def main():
    await app.start()
    await userbot.start()
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
