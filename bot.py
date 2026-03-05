import asyncio
import logging
import re
import random
import os
import json
from pyrogram import Client, filters, idle
from pyrogram.errors import (
    FloodWait, SessionPasswordNeeded, PhoneCodeInvalid,
    PhoneCodeExpired, PasswordHashInvalid, UserAlreadyParticipant
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8309447910:AAFjPO_GzbbNVB50fqxCVady1lkvRSX3cXY"
DATA_FILE = "data.json"

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

BATCH_TASKS = {}
USER_STATE = {}
LOGIN_CACHE = {}  # Temporary storage for login process
ACTIVE_USERBOTS = {} # Store running userbot instances
PROCESSED_ALBUMS = []

# ================= DATA MANAGEMENT =================

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

async def get_userbot(user_id):
    """Returns active userbot for the user, initializes if needed."""
    user_id = str(user_id)
    if user_id in ACTIVE_USERBOTS:
        return ACTIVE_USERBOTS[user_id]
    
    data = load_data()
    if user_id in data and "session" in data[user_id]:
        ubot = Client(
            f"user_{user_id}", 
            api_id=API_ID, 
            api_hash=API_HASH, 
            session_string=data[user_id]["session"],
            in_memory=True
        )
        await ubot.start()
        ACTIVE_USERBOTS[user_id] = ubot
        return ubot
    return None

# ================= SMART UTILS =================

async def resolve_chat(userbot, link_or_id: str):
    link_or_id = str(link_or_id).strip().rstrip("/")
    if re.match(r"^-?\d+$", link_or_id): return int(link_or_id)
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            return int("-100" + parts[parts.index('c') + 1])
        except: pass
    if "+" in link_or_id or "joinchat" in link_or_id:
        try:
            try: await userbot.join_chat(link_or_id)
            except UserAlreadyParticipant: pass
            chat_info = await userbot.get_chat(link_or_id)
            return chat_info.id
        except: return None
    try:
        username = link_or_id.split('/')[-1]
        try: await userbot.join_chat(username)
        except: pass
        chat = await userbot.get_chat(username)
        return chat.id
    except: return None

async def get_thumb(userbot, msg):
    if not msg: return None
    try:
        if msg.photo: return None 
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
    status = '🟢 Running' if t['running'] else '🛑 Stopped'
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 Stop Task", callback_data=f"kill_{task_id}")]])
        )
    except: pass

async def run_batch_worker(task_id, userbot):
    while task_id in BATCH_TASKS and BATCH_TASKS[task_id]['running']:
        t = BATCH_TASKS[task_id]
        try:
            msg = await userbot.get_messages(t['source'], t['current'])
            
            if not msg or msg.empty:
                try:
                    last_msgs = await userbot.get_history(t['source'], limit=1)
                    if last_msgs and t['current'] > last_msgs[0].id:
                        await update_live_report(task_id, "👀 Waiting for New Messages...")
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

            # ================== ALBUM HANDLING ==================
            if msg.media_group_id:
                if msg.media_group_id in PROCESSED_ALBUMS:
                    t['current'] += 1
                    continue
                
                await update_live_report(task_id, "📥 Processing Album...")
                try:
                    media_group = await userbot.get_media_group(t['source'], msg.id)
                    PROCESSED_ALBUMS.append(msg.media_group_id)
                    if len(PROCESSED_ALBUMS) > 100: PROCESSED_ALBUMS.pop(0) 
                    last_id = max([m.id for m in media_group])
                    
                    try:
                        await userbot.copy_media_group(t['dest'], t['source'], msg.id)
                        t['total'] += len(media_group)
                    except Exception:
                        # FALLBACK FOR RESTRICTED CHATS
                        await update_live_report(task_id, f"📥 Downloading Restricted Album...")
                        input_media_list = []
                        files_to_clean = []
                        
                        for m in media_group:
                            file_path = await userbot.download_media(m)
                            if not file_path: continue
                            files_to_clean.append(file_path)
                            
                            thumb_path = await get_thumb(userbot, m)
                            if thumb_path: files_to_clean.append(thumb_path)
                            
                            caption = m.caption or ""
                            
                            if m.photo:
                                input_media_list.append(InputMediaPhoto(media=file_path, caption=caption))
                            elif m.video:
                                input_media_list.append(InputMediaVideo(media=file_path, caption=caption, thumb=thumb_path, duration=m.video.duration, width=m.video.width, height=m.video.height, supports_streaming=True))
                            elif m.document:
                                input_media_list.append(InputMediaDocument(media=file_path, caption=caption, thumb=thumb_path))
                            elif m.audio:
                                input_media_list.append(InputMediaAudio(media=file_path, caption=caption, thumb=thumb_path, duration=m.audio.duration))

                        if input_media_list:
                            await update_live_report(task_id, "📤 Uploading Album...")
                            await userbot.send_media_group(t['dest'], media=input_media_list)
                            t['total'] += len(media_group)
                        
                        for f in files_to_clean:
                            if os.path.exists(f): os.remove(f)
                            
                    t['current'] = last_id + 1
                    continue
                except Exception as e:
                    t['failed'] += 1
                    t['last_error'] = f"Album: {str(e)[:40]}"
                    t['current'] += 1
                    continue

            # ================== SINGLE MESSAGE ==================
            else:
                try:
                    await userbot.copy_message(t['dest'], t['source'], msg.id)
                    t['total'] += 1
                except Exception:
                    # RESTRICTED CONTENT BYPASS
                    await update_live_report(task_id, "📥 Downloading File...")
                    try:
                        file_path = await userbot.download_media(msg)
                        thumb_path = await get_thumb(userbot, msg)
                        await update_live_report(task_id, "📤 Uploading File...")
                        
                        if msg.photo:
                            await userbot.send_photo(t['dest'], file_path, caption=msg.caption)
                        elif msg.video:
                            await userbot.send_video(t['dest'], file_path, caption=msg.caption, thumb=thumb_path, duration=msg.video.duration, width=msg.video.width, height=msg.video.height, supports_streaming=True)
                        elif msg.document:
                             await userbot.send_document(t['dest'], file_path, caption=msg.caption, thumb=thumb_path)
                        elif msg.voice:
                             await userbot.send_voice(t['dest'], file_path, caption=msg.caption)
                        elif msg.audio:
                             await userbot.send_audio(t['dest'], file_path, caption=msg.caption, thumb=thumb_path, duration=msg.audio.duration)
                        else:
                             if msg.text: await userbot.send_message(t['dest'], msg.text)
                        
                        if file_path and os.path.exists(file_path): os.remove(file_path)
                        if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
                        t['total'] += 1
                    except Exception as e:
                        t['failed'] += 1
                        t['last_error'] = f"Bypass: {str(e)[:40]}"

            t['current'] += 1
            await update_live_report(task_id, "⏳ Waiting...")
            await asyncio.sleep(2.5)

        except FloodWait as e:
            await update_live_report(task_id, f"😴 FloodWait {e.value}s")
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            t['last_error'] = f"Loop: {str(e)[:40]}"
            await asyncio.sleep(5)

# ================= UI HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    text = (
        "🚀 **Pro Media Forwarder**\n\n"
        "✅ **Add Account:** For Downloading Private Contant From group and channel\n"
        "✅ **Restricted Bypass:** Download & Upload\n"
        "✅ **Live Sync:** Auto-forwards new messages\n"
    )
    
    uid = str(message.from_user.id)
    data = load_data()
    
    if uid in data and "session" in data[uid]:
        btns = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Start Task", callback_data="new_batch")],
            [InlineKeyboardButton("📊 Active Tasks", callback_data="view_status")],
            [InlineKeyboardButton("🔄 Re-Login Account", callback_data="login_account")]
        ])
        status = "🟢 Account Connected"
    else:
        btns = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Account", callback_data="login_account")]
        ])
        status = "🔴 No Account Found. Please Add Account."

    await message.reply_text(f"{text}\n\n**Status:** {status}", reply_markup=btns)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    uid = query.from_user.id
    str_uid = str(uid)
    data = query.data

    if data == "login_account":
        USER_STATE[uid] = {"step": "LOGIN_PHONE"}
        await query.message.edit_text("📱 **Enter your Telegram Phone Number with Country Code.**\n\n_Example: +919876543210_")

    elif data == "new_batch":
        USER_STATE[uid] = {"step": "SOURCE"}
        await query.message.edit_text("🔗 **Step 1: Source**\nSend Public/Private Link (e.g., `https://t.me/+AbCd` or `t.me/c/123/100`).")
        
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
    str_uid = str(uid)
    
    if uid not in USER_STATE: return
    step = USER_STATE[uid]["step"]
    
    # --- LOGIN FLOW ---
    if step == "LOGIN_PHONE":
        phone = message.text.strip()
        msg = await message.reply("⏳ Sending OTP...")
        try:
            temp_client = Client(f"temp_{uid}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
            await temp_client.connect()
            code_info = await temp_client.send_code(phone)
            
            LOGIN_CACHE[uid] = {"client": temp_client, "phone": phone, "hash": code_info.phone_code_hash}
            USER_STATE[uid]["step"] = "LOGIN_OTP"
            
            await msg.edit("✅ **OTP Sent!**\n\nPlease enter the OTP you received on Telegram.\n_(If it's 12345, send it as 1 2 3 4 5 to avoid spam protection)_")
        except Exception as e:
            await msg.edit(f"❌ **Error:** `{e}`")
            del USER_STATE[uid]

    elif step == "LOGIN_OTP":
        otp = message.text.replace(" ", "")
        msg = await message.reply("⏳ Verifying OTP...")
        cache = LOGIN_CACHE.get(uid)
        temp_client = cache["client"]
        
        try:
            await temp_client.sign_in(cache["phone"], cache["hash"], otp)
            # Login Success without 2FA
            session_string = await temp_client.export_session_string()
            await temp_client.disconnect()
            
            # Save Data
            db = load_data()
            db[str_uid] = {"phone": cache["phone"], "session": session_string, "2fa": None}
            save_data(db)
            
            del USER_STATE[uid]
            del LOGIN_CACHE[uid]
            await msg.edit("🎉 **Login Successful!**\nUse /start to begin forwarding.")
            
        except SessionPasswordNeeded:
            USER_STATE[uid]["step"] = "LOGIN_PWD"
            await msg.edit("🔐 **2FA Password Required!**\nPlease enter your Two-Step Verification password.")
        except Exception as e:
            await msg.edit(f"❌ **Error:** `{e}`")

    elif step == "LOGIN_PWD":
        pwd = message.text
        msg = await message.reply("⏳ Verifying Password...")
        cache = LOGIN_CACHE.get(uid)
        temp_client = cache["client"]
        
        try:
            await temp_client.check_password(pwd)
            session_string = await temp_client.export_session_string()
            await temp_client.disconnect()
            
            # Save Data
            db = load_data()
            db[str_uid] = {"phone": cache["phone"], "session": session_string, "2fa": pwd}
            save_data(db)
            
            del USER_STATE[uid]
            del LOGIN_CACHE[uid]
            await msg.edit("🎉 **Login Successful with 2FA!**\nUse /start to begin forwarding.")
        except Exception as e:
            await msg.edit(f"❌ **Incorrect Password!**\n`{e}`")

    # --- FORWARDING FLOW ---
    elif step == "SOURCE":
        msg = await message.reply("🔍 **Joining & Resolving Source...**")
        userbot = await get_userbot(uid)
        if not userbot: return await msg.edit("❌ You need to Add Account first!")
        
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
            
        source = await resolve_chat(userbot, link_to_resolve)
        if not source: return await msg.edit("❌ **Invalid Source!**")
        
        USER_STATE[uid] = {"step": "DEST", "source": source, "start": start_id}
        await msg.edit(f"✅ **Source Found!**\nStart ID: `{start_id}`\n\n📥 **Step 2:** Send Destination Link.")

    elif step == "DEST":
        msg = await message.reply("🔍 **Joining & Resolving Destination...**")
        userbot = await get_userbot(uid)
        
        dest = await resolve_chat(userbot, message.text)
        if not dest: return await msg.edit("❌ **Invalid Destination!**")
        
        task_id = random.randint(1000, 9999)
        BATCH_TASKS[task_id] = {
            "source": USER_STATE[uid]['source'], "dest": dest, "current": USER_STATE[uid]['start'],
            "total": 0, "failed": 0, "skipped": 0, "running": True,
            "user_id": uid, "log_msg_id": msg.id, "last_error": "None"
        }
        del USER_STATE[uid]
        await msg.edit(f"🚀 **Task {task_id} Started!**")
        asyncio.create_task(run_batch_worker(task_id, userbot))

async def main():
    await app.start()
    print("--- Pro Forwarder Multi-User Running ---")
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
