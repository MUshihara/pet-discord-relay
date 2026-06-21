import os
import re
import time
import requests
import discord

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "1515803681067634799"))

FIREBASE_URL = "https://pet-finder-9b4e5-default-rtdb.asia-southeast1.firebasedatabase.app"

TARGET_PETS = [
    "Unicorn",
    "Raccoon",
    "Golden Dragonfly",
    "GoldenDragonfly",
]

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

def collect_text(message):
    parts = []

    if message.content:
        parts.append(message.content)

    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)

        if embed.description:
            parts.append(embed.description)

        for field in embed.fields:
            parts.append(str(field.name))
            parts.append(str(field.value))

        if embed.footer and embed.footer.text:
            parts.append(embed.footer.text)

    return "\n".join(parts)

def parse_alert(text):
    pet = None

    for name in TARGET_PETS:
        if re.search(r"\b" + re.escape(name) + r"\b", text, re.IGNORECASE):
            pet = "Golden Dragonfly" if name.lower() == "goldendragonfly" else name
            break

    if not pet:
        return None

    match = re.search(
        r"TeleportToPlaceInstance\(\s*(\d+)\s*,\s*[\"']([^\"']+)[\"']",
        text
    )

    if not match:
        return None

    return {
        "pet": pet,
        "placeId": int(match.group(1)),
        "jobId": match.group(2),
        "source": "Discord",
        "timestamp": int(time.time())
    }

def send_to_firebase(data):
    url = FIREBASE_URL + "/alerts.json"
    response = requests.post(url, json=data, timeout=10)
    print("Sent:", response.status_code, data)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    print(f"Watching channel: {CHANNEL_ID}")

@client.event
async def on_message(message):
    if message.channel.id != CHANNEL_ID:
        return

    text = collect_text(message)
    data = parse_alert(text)

    if data:
        send_to_firebase(data)

client.run(DISCORD_TOKEN)
