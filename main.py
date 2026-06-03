import os, json, asyncio, datetime
import discord
from discord import app_commands
import gspread
from google.oauth2.service_account import Credentials

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]

SHEET_ID = "17QEa2Tgo-5Sy1kxgrgUfzVasuaT_OCWy0a4xC2GFRKA"
CHANNEL_ID = 1511558337760854117

RATING_EMOJIS = {
    "1️⃣": 1,
    "2️⃣": 2,
    "3️⃣": 3,
    "4️⃣": 4,
    "5️⃣": 5
}

scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
google_client = gspread.authorize(creds)

sheet = google_client.open_by_key(SHEET_ID)
games_sheet = sheet.worksheet("games")
ratings_sheet = sheet.worksheet("ratings")

intents = discord.Intents.default()
intents.reactions = True
intents.guilds = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def get_all_games():
    rows = games_sheet.get_all_values()[1:]
    return rows

def get_game_by_message_id(message_id):
    rows = games_sheet.get_all_values()[1:]
    for row in rows:
        while len(row) < 5:
            row.append("")
        game, release, console, posted, msg_id = row[:5]
        if str(msg_id) == str(message_id):
            return game
    return None

def upsert_rating(user_id, username, game, rating):
    rows = ratings_sheet.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        while len(row) < 5:
            row.append("")
        if row[1] == str(user_id) and row[3] == game:
            ratings_sheet.update(f"A{i}:E{i}", [[
                datetime.datetime.now().isoformat(),
                str(user_id),
                username,
                game,
                rating
            ]])
            return

    ratings_sheet.append_row([
        datetime.datetime.now().isoformat(),
        str(user_id),
        username,
        game,
        rating
    ])

def remove_rating(user_id, game):
    rows = ratings_sheet.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        while len(row) < 5:
            row.append("")
        if row[1] == str(user_id) and row[3] == game:
            ratings_sheet.delete_rows(i)
            return

async def sync_games():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while not client.is_closed():
        try:
            rows = games_sheet.get_all_values()[1:]

            for i, row in enumerate(rows, start=2):
                while len(row) < 5:
                    row.append("")

                game, release, console, posted, message_id = row[:5]

                if not game.strip():
                    continue

                if str(posted).strip().lower() != "true":
                    msg = await channel.send(
                        f"🎮 **{game}**\n"
                        f"📅 Release: {release}\n"
                        f"🕹️ Platforms: {console}\n\n"
                        f"Rate this game with 1️⃣-5️⃣ below!\n"
                        f"Use the thread to discuss or write your review."
                    )

                    for emoji in RATING_EMOJIS:
                        await msg.add_reaction(emoji)

                    await msg.create_thread(name=f"{game} Discussion")

                    games_sheet.update(f"D{i}:E{i}", [["TRUE", str(msg.id)]])
                    print(f"Posted: {game}")

        except Exception as e:
            print(f"Sync error: {e}")

        await asyncio.sleep(60)

@client.event
async def on_raw_reaction_add(payload):
    if payload.user_id == client.user.id:
        return

    emoji = str(payload.emoji)
    if emoji not in RATING_EMOJIS:
        return

    game = get_game_by_message_id(payload.message_id)
    if not game:
        return

    guild = client.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id) if guild else None
    username = member.display_name if member else str(payload.user_id)

    upsert_rating(payload.user_id, username, game, RATING_EMOJIS[emoji])

@client.event
async def on_raw_reaction_remove(payload):
    emoji = str(payload.emoji)
    if emoji not in RATING_EMOJIS:
        return

    game = get_game_by_message_id(payload.message_id)
    if not game:
        return

    remove_rating(payload.user_id, game)

@tree.command(name="rankings", description="Show current game rankings")
async def rankings(interaction: discord.Interaction):
    rows = ratings_sheet.get_all_values()[1:]
    data = {}

    for row in rows:
        while len(row) < 5:
            row.append("")
        game = row[3]
        rating = int(row[4])
        data.setdefault(game, []).append(rating)

    if not data:
        await interaction.response.send_message("No ratings yet.")
        return

    results = []
    for game, ratings in data.items():
        avg = sum(ratings) / len(ratings)
        results.append((game, avg, len(ratings)))

    results.sort(key=lambda x: x[1], reverse=True)

    msg = "🏆 **Current Game Rankings**\n\n"
    for i, (game, avg, count) in enumerate(results, 1):
        msg += f"{i}. **{game}** — {avg:.1f} ⭐ ({count} votes)\n"

    await interaction.response.send_message(msg)

@tree.command(name="monthly_rankings", description="Show this month's top games")
async def monthly_rankings(interaction: discord.Interaction):
    rows = ratings_sheet.get_all_values()[1:]
    now = datetime.datetime.now()
    data = {}

    for row in rows:
        while len(row) < 5:
            row.append("")
        timestamp, user_id, username, game, rating = row[:5]
        dt = datetime.datetime.fromisoformat(timestamp)

        if dt.month == now.month and dt.year == now.year:
            data.setdefault(game, []).append(int(rating))

    if not data:
        await interaction.response.send_message("No ratings this month yet.")
        return

    results = []
    for game, ratings in data.items():
        avg = sum(ratings) / len(ratings)
        results.append((game, avg, len(ratings)))

    results.sort(key=lambda x: x[1], reverse=True)

    msg = "📅 **Top Games This Month**\n\n"
    for i, (game, avg, count) in enumerate(results, 1):
        msg += f"{i}. **{game}** — {avg:.1f} ⭐ ({count} votes)\n"

    await interaction.response.send_message(msg)

@tree.command(name="backlog", description="Show games you haven't reviewed yet")
async def backlog(interaction: discord.Interaction):
    user_id = str(interaction.user.id)

    games = [row[0] for row in get_all_games() if row and row[0]]
    rows = ratings_sheet.get_all_values()[1:]

    reviewed = set()
    for row in rows:
        while len(row) < 5:
            row.append("")
        if row[1] == user_id:
            reviewed.add(row[3])

    missing = [game for game in games if game not in reviewed]

    if not missing:
        await interaction.response.send_message("You’ve reviewed everything 🎉", ephemeral=True)
        return

    msg = "🎮 **Games You Haven’t Reviewed Yet**\n\n"
    for game in missing:
        msg += f"• {game}\n"

    await interaction.response.send_message(msg, ephemeral=True)

@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user}")
    client.loop.create_task(sync_games())

client.run(DISCORD_TOKEN)
