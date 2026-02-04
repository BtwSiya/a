import asyncio
import logging
import random
import re
import pyromod.listen # Required at the top to prevent KeyError
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait, RPCError, UserAlreadyParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8573758498:AAEplnYzHwUmjYRFiRSdCAFwyPfYIjk7RIk"
SESSION_STRING = "BQFLMbAAb_m5J6AV43eGHnXxxkz8mVJFBOTLcZay_IX7YtklY4S9Z6E0XjPUUoIoM33-BocBlogwRsQsdA8u9YeuLMu1Cmuws3OZISIv3xLz_vAJJAk6mmqeflAkh5X35T6QP-SnbSnd-9FD-fWdP7GyKoJMIrV37RbPym31xaSdOOJjzlf781CIwcoxvTnjqcWzyWlhQS0I7o7nVbmDDCR7rBTlmkMHiN1IjFpxg2Itcc5XjdbG-2JlCOuomw7iWwk3WF-tTbHXCBXNgFEXBzx7mnrY9jr9sCtnx4UHsqq4NiofutkrcX0aZ-TYTwf5RhfGonZjBaHaNZ-lkrREC4YHfqLoWQAAAAGd7PcCAA"

# Set logging to ERROR to keep the console clean and fast
logging.basicConfig(level=logging.ERROR)

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

# ================= FORWARDING ENGINE =================

async def run_batch_worker(task_id):
    task = BATCH_TASKS[task_id]
    while BATCH_TASKS.get(task_id) and BATCH_TASKS[task_id]['running']:
        try:
            msg = await userbot.get_messages(task['source'], task['current'])
            
            if not msg or msg.empty:
                await asyncio.sleep(2) # Pulse check for new messages
                continue

            if not msg.service:
                try:
                    await userbot.copy_message(task['dest'], task['source'], msg.id)
                    await asyncio.sleep(2) # Fixed 2-second interval
                except FloodWait as e:
                    await asyncio.sleep(e.value + 1)
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

# ================= BOT COMMANDS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    text = (
        f"👋 **Greetings {message.from_user.first_name}!**\n\n"
        "I am your dedicated **High-Speed Message Forwarder**.\n"
        "I support Private Links, Restricted Content, and Real-time forwarding.\n\n"
        "⚡ **Pulse Interval:** `2 Seconds`"
    )
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 New Forwarding Batch", callback_data="new_batch")],
        [InlineKeyboardButton("📂 Active Task Manager", callback_data="view_status")]
    ])
    await message.reply_text(text, reply_markup=btns)

@app.on_callback_query()
async def query_processor(client, query: CallbackQuery):
    uid = query.from_user.id

    if query.data == "new_batch":
        await query.message.delete()
        
        try:
            src_ask = await client.ask(uid, "📤 **Step 1:** Send the **Source Link or ID**.\n(Example: `https://t.me/c/123/10`)", timeout=120)
            source_chat = await resolve_chat(src_ask.text)
            start_id = extract_msg_id(src_ask.text)
            
            if not source_chat:
                return await client.send_message(uid, "❌ **Error:** Could not resolve Source. Ensure Userbot has access.")

            dest_ask = await client.ask(uid, "📥 **Step 2:** Send the **Destination Link or ID**.", timeout=120)
            dest_chat = await resolve_chat(dest_ask.text)
            
            if not dest_chat:
                return await client.send_message(uid, "❌ **Error:** Destination unreachable.")

            tid = random.randint(100, 999)
            BATCH_TASKS[tid] = {
                "source": source_chat, "dest": dest_chat,
                "current": start_id, "running": True, "user_id": uid
            }
            
            asyncio.create_task(run_batch_worker(tid))
            await client.send_message(uid, f"✅ **Batch {tid} Started!**\n\nForwarding initiated with a 2-second delay.")
        except asyncio.TimeoutError:
            await client.send_message(uid, "⚠️ **Session Timeout.** Please restart the process.")

    elif query.data == "view_status":
        active = [f"🔹 **ID:** `{tid}` | **Msg:** `{data['current']}`" for tid, data in BATCH_TASKS.items() if data['running'] and data['user_id'] == uid]
        if not active:
            return await query.answer("No active tasks found!", show_alert=True)
        
        txt = "📋 **Your Active Task List:**\n\n" + "\n".join(active)
        btns = [[InlineKeyboardButton(f"🛑 Terminate {t.split('`')[1]}", callback_data=f"stop_{t.split('`')[1]}")] for t in active]
        btns.append([InlineKeyboardButton("🔙 Main Menu", callback_data="back_home")])
        await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(btns))

    elif query.data.startswith("stop_"):
        tid = int(query.data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.answer(f"Task {tid} stopped.", show_alert=True)
            await query.message.edit_text(f"🛑 **Batch {tid}** has been terminated.")

    elif query.data == "back_home":
        await start_handler(client, query.message)

# ================= SYSTEM BOOT =================

async def main():
    print("--- Initializing Hyper-Forwarder ---")
    await app.start()
    await userbot.start()
    print("--- System is LIVE ---")
    await idle()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    
