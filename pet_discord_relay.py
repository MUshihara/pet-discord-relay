import os
import re
import time
import asyncio
import logging

import requests
import discord


# =========================================================
# Logging
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("pet-finder")


# =========================================================
# Configuration
# =========================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
CHANNEL_ID_TEXT = os.getenv(
    "CHANNEL_ID",
    "1515803681067634799",
).strip()

FIREBASE_URL = (
    "https://pet-finder-9b4e5-default-rtdb."
    "asia-southeast1.firebasedatabase.app"
)

TARGET_PETS = [
    "Golden Dragonfly",
    "GoldenDragonfly",
    "Bald Eagle",
    "Firefly",
    "Unicorn",
    "Raccoon",
]

PET_ALIASES = {
    "goldendragonfly": "Golden Dragonfly",
    "golden dragonfly": "Golden Dragonfly",
    "bald eagle": "Bald Eagle",
    "firefly": "Firefly",
    "unicorn": "Unicorn",
    "raccoon": "Raccoon",
}


# =========================================================
# Validate Railway variables before Discord starts
# =========================================================

if not DISCORD_TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is missing. "
        "Add DISCORD_TOKEN in Railway Variables."
    )

try:
    CHANNEL_ID = int(CHANNEL_ID_TEXT)
except ValueError as error:
    raise RuntimeError(
        f"CHANNEL_ID must contain numbers only. "
        f"Current value: {CHANNEL_ID_TEXT!r}"
    ) from error


# =========================================================
# Discord client
# =========================================================

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(
    intents=intents,
    heartbeat_timeout=60,
)


# Prevent the same Discord message from being processed twice
processed_messages = set()


def collect_text(message: discord.Message) -> str:
    parts = []

    if message.content:
        parts.append(message.content)

    for embed in message.embeds:
        if embed.author and embed.author.name:
            parts.append(str(embed.author.name))

        if embed.title:
            parts.append(str(embed.title))

        if embed.description:
            parts.append(str(embed.description))

        for field in embed.fields:
            parts.append(str(field.name))
            parts.append(str(field.value))

        if embed.footer and embed.footer.text:
            parts.append(str(embed.footer.text))

    return "\n".join(parts)


def find_pet(text: str):
    for name in sorted(TARGET_PETS, key=len, reverse=True):
        pattern = (
            r"(?<![A-Za-z0-9_])"
            + re.escape(name)
            + r"(?![A-Za-z0-9_])"
        )

        if re.search(pattern, text, re.IGNORECASE):
            return PET_ALIASES.get(name.lower(), name)

    return None


def parse_alert(text: str):
    pet = find_pet(text)

    if not pet:
        return None

    teleport_match = re.search(
        r"TeleportToPlaceInstance"
        r"\s*\("
        r"\s*(\d+)"
        r"\s*,"
        r"\s*[\"']([^\"']+)[\"']",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if not teleport_match:
        logger.warning(
            "A target pet was detected, but no valid "
            "TeleportToPlaceInstance script was found."
        )
        return None

    place_id = int(teleport_match.group(1))
    job_id = teleport_match.group(2).strip()

    if not job_id:
        return None

    return {
        "pet": pet,
        "placeId": place_id,
        "jobId": job_id,
        "source": "Discord",
        "timestamp": int(time.time()),
    }


def firebase_post_sync(data: dict):
    url = f"{FIREBASE_URL}/alerts.json"

    response = requests.post(
        url,
        json=data,
        timeout=15,
    )

    response.raise_for_status()
    return response


async def send_to_firebase(data: dict):
    try:
        response = await asyncio.to_thread(
            firebase_post_sync,
            data,
        )

        logger.info(
            "Firebase alert sent | Pet=%s | PlaceId=%s | "
            "JobId=%s | Status=%s",
            data["pet"],
            data["placeId"],
            data["jobId"],
            response.status_code,
        )

    except requests.Timeout:
        logger.error("Firebase request timed out.")

    except requests.HTTPError as error:
        response = error.response

        logger.error(
            "Firebase rejected the alert | Status=%s | Body=%s",
            response.status_code if response else "unknown",
            response.text if response else str(error),
        )

    except requests.RequestException as error:
        logger.error("Firebase connection failed: %s", error)

    except Exception:
        logger.exception(
            "Unexpected error while sending to Firebase."
        )


async def process_message(message: discord.Message):
    if message.id in processed_messages:
        return

    text = collect_text(message)

    if not text.strip():
        return

    data = parse_alert(text)

    if not data:
        return

    processed_messages.add(message.id)

    # Prevent this set from growing forever
    if len(processed_messages) > 5000:
        processed_messages.clear()
        processed_messages.add(message.id)

    logger.info(
        "Target detected | Pet=%s | PlaceId=%s | JobId=%s",
        data["pet"],
        data["placeId"],
        data["jobId"],
    )

    await send_to_firebase(data)


@client.event
async def on_ready():
    logger.info("Logged in as %s", client.user)
    logger.info("Watching Discord channel %s", CHANNEL_ID)

    channel = client.get_channel(CHANNEL_ID)

    if channel is None:
        logger.warning(
            "The bot cannot find channel %s. "
            "Check the CHANNEL_ID and bot permissions.",
            CHANNEL_ID,
        )
    else:
        logger.info("Channel found: %s", channel)


@client.event
async def on_message(message: discord.Message):
    try:
        if message.author == client.user:
            return

        if message.channel.id != CHANNEL_ID:
            return

        await process_message(message)

    except Exception:
        # Prevent one malformed Discord message from crashing the bot
        logger.exception(
            "Failed to process Discord message %s",
            message.id,
        )


@client.event
async def on_message_edit(
    before: discord.Message,
    after: discord.Message,
):
    try:
        if after.author == client.user:
            return

        if after.channel.id != CHANNEL_ID:
            return

        # A webhook may first create an empty message,
        # then add or update its embed.
        await process_message(after)

    except Exception:
        logger.exception(
            "Failed to process edited message %s",
            after.id,
        )


@client.event
async def on_error(event_method, *args, **kwargs):
    logger.exception(
        "Discord event error inside %s",
        event_method,
    )


def run_bot():
    logger.info("Starting Grow a Garden 2 Pet Finder...")

    try:
        client.run(
            DISCORD_TOKEN,
            log_handler=None,
        )

    except discord.LoginFailure:
        logger.critical(
            "Discord rejected DISCORD_TOKEN. "
            "Create or copy a valid bot token and update Railway."
        )
        raise

    except discord.PrivilegedIntentsRequired:
        logger.critical(
            "Message Content Intent is not enabled in the "
            "Discord Developer Portal."
        )
        raise

    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")

    except Exception:
        logger.exception("The Discord bot stopped unexpectedly.")
        raise


if __name__ == "__main__":
    run_bot()
