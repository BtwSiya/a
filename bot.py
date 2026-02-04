import asyncio
import logging
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait, RPCError

# ================= CONFIGURATION =================
# YOUR CREDENTIALS HERE
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

# Global Dictionary to control loops: { user_id: False } (True to run, False to stop)
ACTIVE_TASKS = {}

# ================= HELPER FUNCTIONS =================

def get_link_data(link: str):
    """
    Extracts Chat ID and Start Message ID from a link.
    Returns: (chat_id, message_id) or (None, None)
    """
    try:
        if "t.me/c/" in link:
            # Format: https://t.me/c/123456789/100
            parts = link.split("/")
            chat_id = int("-100" + parts[4])
            msg_id = int(parts[5])
            return chat_id, msg_id
        elif "t.me/" in link:
            # Format: https://t.me/username/100
            parts = link.split("/")
            username = parts[-2]
            msg_id = int(parts[-1])
            return username, msg_id
    except Exception:
        return None, None
    return None, None

# ================= CORE BATCH ENGINE =================

async def run_batch_process(bot_client, user_id, source_chat, dest_chat, start_id):
    """
    Loops strictly: 1 -> 2 -> 3. 
    If message doesn't exist yet, it waits (polling), handling future messages.
    """
    current_id = start_id
    status_msg = await bot_client.send_message(
        user_id, 
        f"🚀 **Batch Started!**\n\n**Source:** `{source_chat}`\n**Dest:** `{dest_chat}`\n**Current Msg:** `{current_id}`"
    )

    while ACTIVE_TASKS.get(user_id, False):
        try:
            # 1. Try to get the message using USERBOT (Access restricted channels)
            message = await userbot.get_messages(source_chat, current_id)
            
            # 2. Check if message exists (or is empty service message)
            if not message or message.empty:
                # Message doesn't exist yet (Future Message). Wait and retry.
                # This acts as the "Auto Forwarder" for new messages.
                await asyncio.sleep(5) 
                continue

            # 3. Skip Service messages (like 'Pinned message', 'Joined group')
            if message.service:
                current_id += 1
                continue

            # 4. Copy the message
            try:
                # We use USERBOT to copy because it can access restricted content
                await userbot.copy_message(
                    chat_id=dest_chat,
                    from_chat_id=source_chat,
                    message_id=current_id
                )
                # Log for debugging
                print(f"Copied: {current_id}")
                
                # Update status every 20 messages to avoid FloodWait on status edit
                if current_id % 20 == 0:
                    try:
                        await status_msg.edit_text(f"⚡ **Running...**\n\n**Copied up to:** `{current_id}`")
                    except:
                        pass
                
                # Move to next message
                current_id += 1
                await asyncio.sleep(2) # Safe delay

            except FloodWait as fw:
                print(f"Sleeping {fw.value}s due to FloodWait")
                await asyncio.sleep(fw.value)
            except Exception as e:
                print(f"Failed to copy {current_id}: {e}")
                # If fail (e.g. deleted message), skip it
                current_id += 1

        except FloodWait as fw:
            await asyncio.sleep(fw.value)
        except Exception as e:
            print(f"Global Error: {e}")
            await asyncio.sleep(5)

    await bot_client.send_message(user_id, f"🛑 **Batch Process Stopped.**\nLast processed ID: `{current_id}`")

# ================= BOT COMMANDS =================

@app.on_message(filters.command("start") & filters.private)
async def start_command(_, message):
    await message.reply(
        "👋 **Universal Batch Bot**\n\n"
        "1. Join the Source Channel with your Userbot.\n"
        "2. Add Me (Bot) to the Destination Channel as Admin.\n"
        "3. Send `/batch` to start."
    )

@app.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message):
    user_id = message.chat.id
    
    if ACTIVE_TASKS.get(user_id, False):
        return await message.reply("⚠️ You already have a batch process running! Use `/cancel` first.")

    # 1. Get Source Link
    try:
        ask_source = await client.ask(
            user_id, 
            "**🔗 Send the Start Message Link**\n\n"
            "Example: `https://t.me/c/12345/1001`\n"
            "_(The bot will start copying from this message and continue forever)_"
        )
        if ask_source.text == "/cancel": return await message.reply("Cancelled.")
    except: return

    source_chat, start_msg_id = get_link_data(ask_source.text)
    
    if not source_chat or not start_msg_id:
        return await message.reply("❌ Invalid Link format. Please use a link like `https://t.me/c/xxxx/xxxx`")

    # 2. Get Destination ID
    try:
        ask_dest = await client.ask(
            user_id, 
            "**📤 Send Destination Channel ID**\n"
            "Example: `-1001234567890`"
        )
        if ask_dest.text == "/cancel": return await message.reply("Cancelled.")
        dest_chat = int(ask_dest.text)
    except: return await message.reply("❌ Invalid ID.")

    # 3. Start the Loop
    ACTIVE_TASKS[user_id] = True
    
    # Run loop in background
    asyncio.create_task(run_batch_process(client, user_id, source_chat, dest_chat, start_msg_id))


@app.on_message(filters.command("cancel") & filters.private)
async def cancel_command(_, message):
    user_id = message.chat.id
    if user_id in ACTIVE_TASKS and ACTIVE_TASKS[user_id]:
        ACTIVE_TASKS[user_id] = False
        await message.reply("🛑 Stopping the batch process... (might take a few seconds)")
    else:
        await message.reply("❓ No active process found.")

# ================= MAIN =================

async def main():
    print("Starting Clients...")
    await app.start()
    await userbot.start()
    print("✅ Bot is Alive!")
    await idle()
    await app.stop()
    await userbot.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    
