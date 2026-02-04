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

# Pyromod setup
from pyromod import listen 

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

BATCH_TASKS = {}

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

# ================= CORE ENGINE =================

async def run_batch_worker(task_id):
    """
    Unified worker: handles both backlog and pauses 
    elegantly to prevent double forwarding.
    """
    task = BATCH_TASKS[task_id]
    
    while BATCH_TASKS.get(task_id) and BATCH_TASKS[task_id]['running']:
        try:
            msg = await userbot.get_messages(task['source'], task['current'])
            
            # If no message yet, wait for the next pulse
            if not msg or msg.empty:
                await asyncio.sleep(5) 
                continue

            if not msg.service:
                try:
                    # Cloning Restricted/Normal Content
                    await userbot.copy_message(task['dest'], task['source'], msg.id)
                    await asyncio.sleep(3) # Anti-Flood Delay
                except FloodWait as e:
                    await asyncio.sleep(e.value + 2)
                except Exception:
                    pass

            # Move pointer forward after successful processing/skip
            task['current'] += 1

        except Exception:
            await asyncio.sleep(5)

# Note: Realtime listener is removed to prevent Double Forwarding. 
# The Worker above is now fast enough to catch new messages naturally.

# ================= HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    text = (
        "🚀 **Enterprise Forwarder System**\n\n"
        "Status: `Operational ✅` (24/7)\n"
        "Protection: `Flood-Safety Active 🛡️`\n"
        "Delay: `3 Seconds Interval`"
    )
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Start New Task", callback_data="new_batch")],
        [InlineKeyboardButton("📊 System Monitor", callback_data="view_status")]
    ])
    await message.reply_text(text, reply_markup=btns)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    uid = query.from_user.id

    if query.data == "new_batch":
        await query.message.delete()
        try:
            # Step 1
            src_ask = await client.ask(uid, "📤 **Step 1:**\nSend the **Source Link** or **Chat ID**.\n(Example: `https://t.me/c/123/10`)", timeout=120)
            source_chat = await resolve_chat(src_ask.text)
            start_id = extract_msg_id(src_ask.text)
            if not source_chat: return await client.send_message(uid, "❌ **Error:** Source invalid or unreachable.")

            # Step 2
            dest_ask = await client.ask(uid, "📥 **Step 2:**\nSend the **Destination Link** or **Chat ID**.", timeout=120)
            dest_chat = await resolve_chat(dest_ask.text)
            if not dest_chat: return await client.send_message(uid, "❌ **Error:** Destination invalid.")

            task_id = random.randint(100, 999)
            BATCH_TASKS[task_id] = {
                "source": source_chat, "dest": dest_chat,
                "current": start_id, "running": True, "user_id": uid
            }
            
            asyncio.create_task(run_batch_worker(task_id))
            await client.send_message(uid, f"✅ **Task {task_id} Initiated!**\nCloning started from message `{start_id}`.")
        
        except asyncio.TimeoutError:
            await client.send_message(uid, "⚠️ **Session Expired:** Request timed out.")

    elif query.data == "view_status":
        active = [f"🔹 `Task {tid}` | Index: `{data['current']}`" for tid, data in BATCH_TASKS.items() if data['running'] and data['user_id'] == uid]
        if not active: return await query.answer("No active processes!", show_alert=True)
        
        txt = "📊 **Live System Monitor:**\n\n" + "\n".join(active)
        btns = [[InlineKeyboardButton(f"🛑 Terminate {t.split(' ')[1]}", callback_data=f"stop_{t.split(' ')[1].replace('`','')}") ] for t in active]
        btns.append([InlineKeyboardButton("🔙 Menu", callback_data="back_home")])
        await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(btns))

    elif query.data.startswith("stop_"):
        tid = int(query.data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.answer(f"Process {tid} terminated.", show_alert=True)
            await query.message.delete()

    elif query.data == "back_home":
        await start_handler(client, query.message)

# ================= BOOT =================

async def boot():
    await app.start()
    await userbot.start()
    print("Forwarder is Online. Double-post fix applied.")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(boot())
    
