import asyncio
import logging
import random
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait, RPCError
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8573758498:AAEplnYzHwUmjYRFiRSdCAFwyPfYIjk7RIk"
SESSION_STRING = "BQFLMbAAb_m5J6AV43eGHnXxxkz8mVJFBOTLcZay_IX7YtklY4S9Z6E0XjPUUoIoM33-BocBlogwRsQsdA8u9YeuLMu1Cmuws3OZISIv3xLz_vAJJAk6mmqeflAkh5X35T6QP-SnbSnd-9FD-fWdP7GyKoJMIrV37RbPym31xaSdOOJjzlf781CIwcoxvTnjqcWzyWlhQS0I7o7nVbmDDCR7rBTlmkMHiN1IjFpxg2Itcc5XjdbG-2JlCOuomw7iWwk3WF-tTbHXCBXNgFEXBzx7mnrY9jr9sCtnx4UHsqq4NiofutkrcX0aZ-TYTwf5RhfGonZjBaHaNZ-lkrREC4YHfqLoWQAAAAGd7PcCAA"

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Clients
app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# ================= GLOBAL STORAGE =================
# Stores details of all running batches
# Format: { task_id: { "user_id": 123, "source": -100x, "dest": -100y, "current": 100, "running": True } }
BATCH_TASKS = {}

# ================= HELPER FUNCTIONS =================

def get_link_data(link: str):
    try:
        if "t.me/c/" in link:
            parts = link.split("/")
            chat_id = int("-100" + parts[4])
            msg_id = int(parts[5])
            return chat_id, msg_id
        elif "t.me/" in link:
            parts = link.split("/")
            username = parts[-2]
            msg_id = int(parts[-1])
            return username, msg_id
    except:
        return None, None
    return None, None

# ================= CORE BATCH ENGINE =================

async def run_batch_process(bot_client, task_id):
    """
    Independent worker function for each batch.
    """
    task = BATCH_TASKS[task_id]
    user_id = task['user_id']
    source_chat = task['source']
    dest_chat = task['dest']
    current_id = task['current']

    print(f"[Task {task_id}] Started: {source_chat} -> {dest_chat}")

    while BATCH_TASKS.get(task_id) and BATCH_TASKS[task_id]['running']:
        try:
            # 1. Try fetch message via Userbot (for Restricted Content)
            try:
                message = await userbot.get_messages(source_chat, current_id)
            except RPCError:
                # If cannot get message (e.g. userbot banned or chat invalid)
                await asyncio.sleep(5)
                continue

            # 2. Handle Non-Existent Messages (Future Wait Mode)
            if not message or message.empty:
                # Message doesn't exist yet. Wait for it (Future post)
                await asyncio.sleep(5) 
                continue

            # 3. Skip Service Messages
            if message.service:
                current_id += 1
                BATCH_TASKS[task_id]['current'] = current_id
                continue

            # 4. Copy Message
            try:
                # Using Userbot copy for Restricted Content support
                await userbot.copy_message(
                    chat_id=dest_chat,
                    from_chat_id=source_chat,
                    message_id=current_id
                )
                
                # Log Update
                BATCH_TASKS[task_id]['current'] = current_id + 1
                current_id += 1
                
                # Sleep slightly to prevent flood
                await asyncio.sleep(2) 

            except FloodWait as fw:
                print(f"[Task {task_id}] Sleeping {fw.value}s")
                await asyncio.sleep(fw.value)
            except Exception as e:
                print(f"[Task {task_id}] Copy Error: {e}")
                # Skip message if copy fails (e.g., media too large or permission error)
                current_id += 1
                BATCH_TASKS[task_id]['current'] = current_id

        except Exception as e:
            print(f"[Task {task_id}] Critical Error: {e}")
            await asyncio.sleep(5)

    # If loop breaks
    try:
        await bot_client.send_message(user_id, f"✅ **Batch {task_id} Stopped.**\nLast Processed: `{current_id}`")
    except:
        pass

# ================= BOT COMMANDS =================

@app.on_message(filters.command(["start", "help"]) & filters.private)
async def start_cmd(_, message):
    text = (
        "🤖 **Multi-Task Batch Bot**\n\n"
        "Available Commands:\n"
        "🆕 `/new` - Start a NEW forwarding batch.\n"
        "📊 `/status` - View running batches & Stop them.\n"
        "🛑 `/cancel <id>` - Manually stop a batch by ID."
    )
    await message.reply(text)

@app.on_message(filters.command("new") & filters.private)
async def new_batch(client, message):
    user_id = message.chat.id

    # 1. Ask for Source
    try:
        ask_src = await client.ask(
            user_id, 
            "**🔗 Send the Start Message Link**\n"
            "(`https://t.me/c/xxxx/100`)",
            timeout=60
        )
    except:
        return await message.reply("❌ Time out. Send `/new` again.")
        
    src_chat, start_id = get_link_data(ask_src.text)
    if not src_chat:
        return await message.reply("❌ Invalid Link.")

    # 2. Ask for Destination
    try:
        ask_dest = await client.ask(
            user_id, 
            "**📤 Send Destination Channel ID**\n"
            "(Make sure I am Admin there, e.g., `-100xxxx`)",
            timeout=60
        )
        dest_chat = int(ask_dest.text)
    except:
        return await message.reply("❌ Invalid ID or Timeout.")

    # 3. Create Task
    task_id = random.randint(1000, 9999)
    BATCH_TASKS[task_id] = {
        "user_id": user_id,
        "source": src_chat,
        "dest": dest_chat,
        "current": start_id,
        "running": True
    }

    # 4. Start Background Worker
    asyncio.create_task(run_batch_process(client, task_id))

    await message.reply(
        f"✅ **Batch Started!**\n\n"
        f"🆔 **ID:** `{task_id}`\n"
        f"📂 **Source:** `{src_chat}`\n"
        f"📁 **Dest:** `{dest_chat}`\n"
        f"🚀 **Starting from:** `{start_id}`\n\n"
        f"Check `/status` to manage."
    )

@app.on_message(filters.command("status") & filters.private)
async def status_handler(client, message):
    user_id = message.chat.id
    
    # Filter tasks belonging to this user
    my_tasks = {k: v for k, v in BATCH_TASKS.items() if v['user_id'] == user_id and v['running']}

    if not my_tasks:
        return await message.reply("💤 No active batches running.\nUse `/new` to start one.")

    text = "**📊 Active Batches:**\n\n"
    buttons = []
    
    for tid, data in my_tasks.items():
        text += (
            f"🆔 **{tid}** | 🔄 Msg: `{data['current']}`\n"
            f"From: `{data['source']}` ➡ To: `{data['dest']}`\n"
            f"➖➖➖➖➖➖➖\n"
        )
        # Add Stop Button for this task
        buttons.append([InlineKeyboardButton(f"🛑 Stop Batch {tid}", callback_data=f"stop_{tid}")])

    await message.reply(text, reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex(r"^stop_"))
async def stop_callback(client, callback):
    try:
        task_id = int(callback.data.split("_")[1])
        if task_id in BATCH_TASKS:
            BATCH_TASKS[task_id]['running'] = False
            await callback.answer("✅ Batch Stopped!", show_alert=True)
            await callback.message.edit_text(f"🛑 Batch `{task_id}` has been stopped.")
        else:
            await callback.answer("❌ Batch already stopped or not found.", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error: {e}")

@app.on_message(filters.command("cancel") & filters.private)
async def manual_cancel(client, message):
    try:
        task_id = int(message.command[1])
        if task_id in BATCH_TASKS:
            BATCH_TASKS[task_id]['running'] = False
            await message.reply(f"🛑 **Batch {task_id} Stopped.**")
        else:
            await message.reply("❌ Invalid Batch ID.")
    except:
        await message.reply("⚠️ Usage: `/cancel <batch_id>`\nCheck IDs in `/status`")

# ================= MAIN EXECUTION =================

async def main():
    print("--- Starting Bot & Userbot ---")
    await app.start()
    await userbot.start()
    print("--- 🟢 System Online ---")
    await idle()
    await app.stop()
    await userbot.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
