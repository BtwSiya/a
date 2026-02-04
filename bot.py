import asyncio
import logging
import random
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait, RPCError
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8573758498:AAEplnYzHwUmjYRFiRSdCAFwyPfYIjk7RIk"
SESSION_STRING = "BQFLMbAAb_m5J6AV43eGHnXxxkz8mVJFBOTLcZay_IX7YtklY4S9Z6E0XjPUUoIoM33-BocBlogwRsQsdA8u9YeuLMu1Cmuws3OZISIv3xLz_vAJJAk6mmqeflAkh5X35T6QP-SnbSnd-9FD-fWdP7GyKoJMIrV37RbPym31xaSdOOJjzlf781CIwcoxvTnjqcWzyWlhQS0I7o7nVbmDDCR7rBTlmkMHiN1IjFpxg2Itcc5XjdbG-2JlCOuomw7iWwk3WF-tTbHXCBXNgFEXBzx7mnrY9jr9sCtnx4UHsqq4NiofutkrcX0aZ-TYTwf5RhfGonZjBaHaNZ-lkrREC4YHfqLoWQAAAAGd7PcCAA"

logging.basicConfig(level=logging.INFO)

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# { task_id: { "source": int, "dest": int, "current": int, "running": bool } }
BATCH_TASKS = {}

# ================= UTILS =================

async def get_chat_id(link: str):
    """Resolves any link (private/public) to a Chat ID."""
    if "t.me/c/" in link:
        return int("-100" + link.split("/")[4])
    elif "t.me/" in link:
        username = link.split("/")[-1]
        try:
            chat = await userbot.get_chat(username)
            return chat.id
        except:
            return None
    return None

def extract_msg_id(link: str):
    try:
        return int(link.split("/")[-1])
    except:
        return None

# ================= CORE ENGINE =================

async def run_batch_worker(task_id):
    task = BATCH_TASKS[task_id]
    source = task['source']
    dest = task['dest']
    current = task['current']

    while BATCH_TASKS.get(task_id) and BATCH_TASKS[task_id]['running']:
        try:
            msg = await userbot.get_messages(source, current)
            
            if not msg or msg.empty:
                # Wait for future messages
                await asyncio.sleep(5)
                continue

            if not msg.service:
                try:
                    await userbot.copy_message(dest, source, current)
                    await asyncio.sleep(1.5) # Anti-spam delay
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                except Exception:
                    pass

            current += 1
            BATCH_TASKS[task_id]['current'] = current

        except Exception:
            await asyncio.sleep(5)

# Real-time listener for "Instant" forwarding of new posts
@userbot.on_message(filters.incoming)
async def instant_forwarder(client, message):
    for tid, task in BATCH_TASKS.items():
        if task['running'] and message.chat.id == task['source']:
            try:
                # If the incoming message is newer than our current loop, copy it instantly
                if message.id >= task['current']:
                    await userbot.copy_message(task['dest'], message.chat.id, message.id)
            except:
                pass

# ================= HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    welcome_text = (
        "✨ **Welcome to Premium Forwarder Bot** ✨\n\n"
        "🚀 I can forward messages from restricted channels and groups in real-time.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📍 **Status:** `Online Baby`\n"
        "📍 **Mode:** `Batch + Instant ⚡`"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Start New Batch", callback_data="new_batch")],
        [InlineKeyboardButton("📊 My Batches", callback_data="view_status")],
        [InlineKeyboardButton("🛠 Support", url="https://t.me/iscxm")]
    ])
    await message.reply(welcome_text, reply_markup=buttons)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    user_id = query.from_user.id

    if query.data == "new_batch":
        await query.message.delete()
        
        # 1. Source Link
        src_ask = await client.ask(user_id, "🔗 **Step 1:** Send the **Start Link** from Source.\n(e.g., `https://t.me/c/123/10`)", timeout=60)
        source_chat = await get_chat_id(src_ask.text)
        start_id = extract_msg_id(src_ask.text)
        
        if not source_chat or not start_id:
            return await client.send_message(user_id, "❌ **Invalid Link!** Start again with /start")

        # 2. Destination Link
        dest_ask = await client.ask(user_id, "📥 **Step 2:** Send the **Destination Link**.\n(e.g., `https://t.me/my_group`)", timeout=60)
        dest_chat = await get_chat_id(dest_ask.text)
        
        if not dest_chat:
            return await client.send_message(user_id, "❌ **Invalid Destination!** Make sure your Userbot is in that group.")

        # Start Task
        task_id = random.randint(1000, 9999)
        BATCH_TASKS[task_id] = {
            "source": source_chat,
            "dest": dest_chat,
            "current": start_id,
            "running": True,
            "user_id": user_id
        }
        
        asyncio.create_task(run_batch_worker(task_id))
        
        await client.send_message(user_id, f"✅ **Batch {task_id} Active!**\n🚀 Now forwarding old and new messages.")

    elif query.data == "view_status":
        my_tasks = {k: v for k, v in BATCH_TASKS.items() if v.get('user_id') == user_id and v['running']}
        if not my_tasks:
            return await query.answer("No active batches!", show_alert=True)
        
        status_text = "📊 **Active Processing List:**\n\n"
        buttons = []
        for tid, data in my_tasks.items():
            status_text += f"🔹 **ID:** `{tid}` | **Current:** `{data['current']}`\n"
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
    print("Initializing...")
    await app.start()
    await userbot.start()
    print("Bot Started Successfully!")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(boot())
    
