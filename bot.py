import asyncio
import logging
import random
import re
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait, RPCError, UserAlreadyParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8572528424:AAErREWZ0rxRYnzyJw06dRgOsrwQRcEhlkc"
SESSION_STRING = "BQFGCokAgeUYbfqZyyM_tUlZOL9e4XM-eNqZX7_433fLwjvGB4SKL2YC6GBy-7S8ySKF4mwvaFE3FoUPQBrptI68vigVx7RBBwcUlV8LjHDK7CDuyin3nF8vIusS6g3ujLgQBBKajb7IhGPQVOMm-9q2kdROazENzXx-BHPVr3XaSeLM3gtPnY1T_y_RukGosNOfHTfwMkD0oS7fj0zl6KNwO4OgQEAFzTXmfpw9cAW9hCItiT16Q9UE9E75IhekfoPxCSVgwYt35fN7FCPzz8hQNIQwSLikifoeb5XAYSBGHwOnwIdiiovPwLZ9cB9tbEE4utODrHCqZLgVNhcTcjRcVod2MwAAAAF5efmpAA"

logging.basicConfig(level=logging.ERROR)

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# Storage
BATCH_TASKS = {}
USER_STATE = {} # Tracking states: {user_id: {"step": 1, "source": None}}

# ================= UTILS =================

async def resolve_chat(link_or_id: str):
    link_or_id = link_or_id.strip()
    if re.match(r"^-?\d+$", link_or_id):
        return int(link_or_id)
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            return int("-100" + parts[parts.index('c') + 1])
        except: return None
    if any(x in link_or_id for x in ["t.me/+", "t.me/joinchat/"]):
        try:
            chat = await userbot.join_chat(link_or_id)
            return chat.id
        except UserAlreadyParticipant:
            chat = await userbot.get_chat(link_or_id)
            return chat.id
        except: return None
    if "t.me/" in link_or_id:
        username = link_or_id.split('/')[-1]
        try:
            chat = await userbot.get_chat(username)
            return chat.id
        except: return None
    return None

def extract_msg_id(link: str):
    try: return int(link.split("/")[-1])
    except: return 1

# ================= ENGINE =================

async def run_batch_worker(task_id):
    task = BATCH_TASKS[task_id]
    while BATCH_TASKS.get(task_id) and BATCH_TASKS[task_id]['running']:
        try:
            msg = await userbot.get_messages(task['source'], task['current'])
            if not msg or msg.empty:
                await asyncio.sleep(2) 
                continue

            if not msg.service:
                try:
                    await userbot.copy_message(task['dest'], task['source'], msg.id)
                    await asyncio.sleep(3) # REQUESTED: 3s Delay
                except FloodWait as e:
                    await asyncio.sleep(e.value + 2)
                except Exception:
                    pass 
            task['current'] += 1
        except Exception:
            await asyncio.sleep(5)

@userbot.on_message(filters.incoming)
async def realtime_handler(client, message):
    for tid, task in BATCH_TASKS.items():
        if task['running'] and message.chat.id == task['source']:
            if message.id >= task['current']:
                try:
                    await userbot.copy_message(task['dest'], task['source'], message.id)
                except: pass

# ================= HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    USER_STATE[message.from_user.id] = None
    text = (
        "✨ **Premium Auto-Forwarder** ✨\n\n"
        "Professional English Alerts & 3s Delay Active.\n"
        "Restricted content support: **Enabled** ✅"
    )
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Start New Batch", callback_data="new_batch")],
        [InlineKeyboardButton("📊 My Batches", callback_data="view_status")]
    ])
    await message.reply_text(text, reply_markup=btns)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    uid = query.from_user.id
    if query.data == "new_batch":
        USER_STATE[uid] = {"step": "SOURCE"}
        await query.message.edit_text("🔗 **Step 1:**\nSend the **Source Link or ID**.")

    elif query.data == "view_status":
        active = [f"🔹 `{tid}`: Msg `{data['current']}`" for tid, data in BATCH_TASKS.items() if data['running'] and data['user_id'] == uid]
        if not active: return await query.answer("No active batches!", show_alert=True)
        txt = "📊 **Active Tasks:**\n\n" + "\n".join(active)
        btns = [[InlineKeyboardButton(f"🛑 Stop {t.split('`')[1]}", callback_data=f"stop_{t.split('`')[1]}")] for t in active]
        btns.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
        await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(btns))

    elif query.data.startswith("stop_"):
        tid = int(query.data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.answer("Stopped!", show_alert=True)
            await query.message.delete()

    elif query.data == "back_home":
        await start_handler(client, query.message)

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE or not USER_STATE[uid]: return

    step = USER_STATE[uid]["step"]
    if step == "SOURCE":
        source = await resolve_chat(message.text)
        start_id = extract_msg_id(message.text)
        if not source: return await message.reply("❌ Invalid Source!")
        USER_STATE[uid] = {"step": "DEST", "source": source, "current": start_id}
        await message.reply("📥 **Step 2:**\nSend the **Destination ID or Link**.")

    elif step == "DEST":
        dest = await resolve_chat(message.text)
        if not dest: return await message.reply("❌ Invalid Destination!")
        
        data = USER_STATE[uid]
        tid = random.randint(100, 999)
        BATCH_TASKS[tid] = {"source": data['source'], "dest": dest, "current": data['current'], "running": True, "user_id": uid}
        
        USER_STATE[uid] = None
        asyncio.create_task(run_batch_worker(tid))
        await message.reply(f"✅ **Batch {tid} Started!**\n3s delay interval active.")

# ================= BOOT =================

async def main():
    await app.start()
    await userbot.start()
    print("Forwarder is Online (No-Pyromod Version)")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    
