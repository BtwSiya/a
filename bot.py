import asyncio
import logging
import random
import re
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait, RPCError, ChatAdminRequired, UserAlreadyParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8573758498:AAEplnYzHwUmjYRFiRSdCAFwyPfYIjk7RIk"
SESSION_STRING = "BQFLMbAAb_m5J6AV43eGHnXxxkz8mVJFBOTLcZay_IX7YtklY4S9Z6E0XjPUUoIoM33-BocBlogwRsQsdA8u9YeuLMu1Cmuws3OZISIv3xLz_vAJJAk6mmqeflAkh5X35T6QP-SnbSnd-9FD-fWdP7GyKoJMIrV37RbPym31xaSdOOJjzlf781CIwcoxvTnjqcWzyWlhQS0I7o7nVbmDDCR7rBTlmkMHiN1IjFpxg2Itcc5XjdbG-2JlCOuomw7iWwk3WF-tTbHXCBXNgFEXBzx7mnrY9jr9sCtnx4UHsqq4NiofutkrcX0aZ-TYTwf5RhfGonZjBaHaNZ-lkrREC4YHfqLoWQAAAAGd7PcCAA"

logging.basicConfig(level=logging.INFO)

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# { task_id: { "source": int, "dest": int, "current": int, "running": bool, "user_id": int } }
BATCH_TASKS = {}

# ================= UTILS =================

async def resolve_chat(link_or_id: str):
    """Resolves IDs, Public Links, and Private Links to Chat IDs."""
    # Agar numeric ID hai (-100...)
    if re.match(r"^-?\d+$", link_or_id):
        return int(link_or_id)
    
    # Private Link: t.me/c/123456789/123
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            return int("-100" + parts[parts.index('c') + 1])
        except:
            return None

    # Invite Link: t.me/+ABCDEFG
    if "t.me/+" in link_or_id or "t.me/joinchat/" in link_or_id:
        try:
            chat = await userbot.join_chat(link_or_id)
            return chat.id
        except UserAlreadyParticipant:
            chat = await userbot.get_chat(link_or_id)
            return chat.id
        except Exception:
            return None

    # Public Link: t.me/username
    if "t.me/" in link_or_id:
        username = link_or_id.split('/')[-1]
        try:
            chat = await userbot.get_chat(username)
            return chat.id
        except Exception:
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
                await asyncio.sleep(5) # Wait for future posts
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

@userbot.on_message(filters.incoming)
async def instant_forwarder(client, message):
    for tid, task in BATCH_TASKS.items():
        if task['running'] and message.chat.id == task['source']:
            try:
                if message.id >= task['current']:
                    await userbot.copy_message(task['dest'], message.chat.id, message.id)
            except:
                pass

# ================= HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    welcome_text = (
        "✨ **Welcome to Premium Forwarder Bot** ✨\n\n"
        "🚀 Private/Public Links aur IDs dono support karta hoon.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📍 **Status:** `Online 🟢` | **Session:** `Active ✅`"
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
        
        # 1. Source Input
        src_ask = await client.ask(user_id, "🔗 **Step 1:** Send the **Source Link or ID**.\n(e.g., `https://t.me/c/123/10` or `-100...`)", timeout=60)
        source_chat = await resolve_chat(src_ask.text)
        start_id = extract_msg_id(src_ask.text) or 1
        
        if not source_chat:
            return await client.send_message(user_id, "❌ **Invalid Source!** Bot ya Userbot ko us chat me hona chahiye.")

        # 2. Destination Input
        dest_ask = await client.ask(user_id, "📥 **Step 2:** Send the **Destination Link or ID**.\n(e.g., `https://t.me/my_group` or `-100...`)", timeout=60)
        dest_chat = await resolve_chat(dest_ask.text)
        
        if not dest_chat:
            return await client.send_message(user_id, "❌ **Invalid Destination!** Userbot ko us group/channel me join hona zaroori hai.")

        # Task Creation
        task_id = random.randint(1000, 9999)
        BATCH_TASKS[task_id] = {
            "source": source_chat,
            "dest": dest_chat,
            "current": start_id,
            "running": True,
            "user_id": user_id
        }
        
        asyncio.create_task(run_batch_worker(task_id))
        await client.send_message(user_id, f"✅ **Batch {task_id} Started!**\n\n🔹 **From:** `{source_chat}`\n🔹 **To:** `{dest_chat}`\n🚀 Old aur New messages ab forward honge.")

    elif query.data == "view_status":
        my_tasks = {k: v for k, v in BATCH_TASKS.items() if v.get('user_id') == user_id and v['running']}
        if not my_tasks:
            return await query.answer("No active batches!", show_alert=True)
        
        status_text = "📊 **Active Processing List:**\n\n"
        buttons = []
        for tid, data in my_tasks.items():
            status_text += f"🔹 **ID:** `{tid}` | **Msg:** `{data['current']}`\n"
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
    print("Bot & Userbot are Online!")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(boot())
        
