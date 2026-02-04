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

logging.basicConfig(level=logging.INFO)

# Pyromod is used for client.ask, ensure 'pip install pyromod' is done.
from pyromod import listen 

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# Global task tracker
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

    if "t.me/+" in link_or_id or "t.me/joinchat/" in link_or_id:
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
    except: return None

# ================= CORE ENGINE =================

async def run_batch_worker(task_id):
    """Old messages ko forward karne ke liye worker."""
    task = BATCH_TASKS[task_id]
    
    while BATCH_TASKS.get(task_id) and BATCH_TASKS[task_id]['running']:
        try:
            msg = await userbot.get_messages(task['source'], task['current'])
            
            if not msg or msg.empty:
                # Agar naya message nahi mila, toh 5 sec wait karke loop fir check karega
                await asyncio.sleep(5)
                continue

            if not msg.service:
                try:
                    await userbot.copy_message(task['dest'], task['source'], msg.id)
                    # REQUESTED: 3 seconds delay for anti-flood
                    await asyncio.sleep(3) 
                except FloodWait as e:
                    await asyncio.sleep(e.value + 5)
                except Exception:
                    pass

            task['current'] += 1

        except Exception as e:
            logging.error(f"Worker Error: {e}")
            await asyncio.sleep(5)

@userbot.on_message(filters.incoming)
async def realtime_forwarder(client, message):
    """Jaise hi naya message aaye, turant forward karne ke liye."""
    for tid, task in BATCH_TASKS.items():
        if task['running'] and message.chat.id == task['source']:
            try:
                # Sirf tab forward karega jab message ID current batch se aage ho
                if message.id >= task['current']:
                    await asyncio.sleep(3) # Anti-flood delay
                    await userbot.copy_message(task['dest'], task['source'], message.id)
            except Exception as e:
                logging.error(f"Realtime Error: {e}")

# ================= HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    welcome_text = (
        "⚡ **Advanced Auto-Forwarder Bot** ⚡\n\n"
        "I will now forward messages with a **3-second delay** to keep your account safe.\n\n"
        "📍 **Status:** `Active ✅`"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Start New Batch", callback_data="new_batch")],
        [InlineKeyboardButton("📊 My Batches", callback_data="view_status")]
    ])
    await message.reply(welcome_text, reply_markup=buttons)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    user_id = query.from_user.id

    if query.data == "new_batch":
        await query.message.delete()
        
        try:
            # Source Input
            src_ask = await client.ask(user_id, "🔗 **Step 1:** Send the **Source Link or ID**.\n(e.g., `https://t.me/c/123/10`)", timeout=120)
            source_chat = await resolve_chat(src_ask.text)
            start_id = extract_msg_id(src_ask.text) or 1
            
            if not source_chat:
                return await client.send_message(user_id, "❌ Invalid Source! Make sure Userbot is in the chat.")

            # Destination Input
            dest_ask = await client.ask(user_id, "📥 **Step 2:** Send the **Destination Link or ID**.", timeout=120)
            dest_chat = await resolve_chat(dest_ask.text)
            
            if not dest_chat:
                return await client.send_message(user_id, "❌ Invalid Destination! Userbot must be a member.")

            task_id = random.randint(1000, 9999)
            BATCH_TASKS[task_id] = {
                "source": source_chat,
                "dest": dest_chat,
                "current": start_id,
                "running": True,
                "user_id": user_id
            }
            
            asyncio.create_task(run_batch_worker(task_id))
            await client.send_message(user_id, f"✅ **Batch {task_id} Started!**\n\n🚀 Every message will be forwarded with a **3-second delay**.")
        
        except asyncio.TimeoutError:
            await client.send_message(user_id, "⚠️ Timeout! Please click 'Start New Batch' again.")

    elif query.data == "view_status":
        my_tasks = {k: v for k, v in BATCH_TASKS.items() if v.get('user_id') == user_id and v['running']}
        if not my_tasks:
            return await query.answer("No active batches!", show_alert=True)
        
        status_text = "📊 **Active Processing List:**\n\n"
        buttons = []
        for tid, data in my_tasks.items():
            status_text += f"🔹 **ID:** `{tid}` | **Next Msg:** `{data['current']}`\n"
            buttons.append([InlineKeyboardButton(f"🛑 Stop {tid}", callback_data=f"stop_{tid}")])
        
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="back_home")])
        await query.message.edit_text(status_text, reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data.startswith("stop_"):
        tid = int(query.data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.answer(f"Task {tid} Stopped!", show_alert=True)
            await query.message.delete()
        
    elif query.data == "back_home":
        await start_handler(client, query.message)

# ================= BOOT =================

async def boot():
    await app.start()
    await userbot.start()
    print("Bot & Userbot are Online with 3s Delay logic!")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(boot())
