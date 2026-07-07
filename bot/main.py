# ./bot/main.py
import asyncio
import os
import logging
from html import escape as html_escape
from datetime import datetime, timedelta
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from bot.mechanics.db import db
from fastapi.encoders import jsonable_encoder
from fastapi import Response
import aiohttp

from bot.rate_limiter import RateLimitedAsyncTeleBot
from telebot.async_telebot import AsyncTeleBot
from bot.handlers.command_handlers import register_command_handlers
from bot.handlers.callback_handlers import register_callback_handlers, ALL_NATURES
from bot.battle.battle_handlers import register_battle_handlers 
from bot.battle.battle_engine import active_battles
from bot.dex.dex_handlers import register_dex_handlers
from bot.showdown_battle import register_showdown_challenge_handlers
from bot.mechanics.moves_loader import SPECIES_BY_ID, LEARNSETS, MOVE_BY_ID
from fastapi.middleware.cors import CORSMiddleware
from bot.mechanics.team import Pokemon, Stats, resolve_full_learnset
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
import traceback
from bot.mechanics.item_data import ALL_ITEMS
from bot.mechanics.ranking import get_rank_details
from bot.image_generation.trainer_card import create_trainer_card_image

# --- Setup logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logging.getLogger("httpcore").setLevel(logging.WARNING)

BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME', 'PokéClash')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set! Please check your .env file.")

bot = RateLimitedAsyncTeleBot(BOT_TOKEN)

app = FastAPI()

def normalize_origin(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.strip().strip('"').rstrip("/")


RENDER_URL = normalize_origin(os.getenv("WEB_APP_HOST_URL"))

origins = [
    "http://localhost:8080",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://127.0.0.1:8080",
]

if RENDER_URL:
    origins.append(RENDER_URL)

origin_regex = r"^https://([a-z0-9-]+\.)?(onrender\.com|trycloudflare\.com)$|^http://(localhost|127\.0\.0\.1)(:\d+)?$"

logging.info("Configured CORS origins: %s", origins)
logging.info("Configured CORS regex: %s", origin_regex)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Model for saving a team ---
class TeamUpdateRequest(BaseModel):
    user_id: int
    team_uuids: List[str]

class PokemonUpdateRequest(BaseModel):
    user_id: int
    pokemon_data: dict

# --- This is the new model for the secure editor ---
class PokemonEditorUpdateRequest(BaseModel):
    user_id: int
    level: int = Field(..., gt=0, le=100) # Enforce level 1-100
    nature: str
    ability: str
    item: Optional[str]
    tera_type: str
    moves: List[str] # A list of move IDs
    evs: Dict[str, int]
    ivs: Dict[str, int]


def get_species_learnset(species_id: str) -> Dict[str, list]:
    return resolve_full_learnset(species_id)


@app.get("/api/user/{user_id}/data")
async def get_user_data(user_id: int):
    """
    Fetches all necessary data for the team editor for a specific user.
    """
    try:
        collection = db.get_collection(user_id)
        teams = db.get_user_teams(user_id)
        active_team_db = db.get_active_team(user_id)
        active_team_id = active_team_db[0] if active_team_db else None
        
        # Convert your list of Pokemon objects to plain dictionaries
        collection_json = jsonable_encoder(collection)
        
        # Loop through and add the 'num' from SPECIES_BY_ID
        for poke_dict in collection_json:
            species_id = poke_dict.get("id")
            species_data = SPECIES_BY_ID.get(species_id)
            
            if species_data:
                # This adds the Pokedex number (e.g., 25 for Pikachu)
                poke_dict["num"] = species_data.get("num")

        return {
            "collection": collection_json, # Now contains the 'num'
            "teams": teams,
            "active_team_id": active_team_id
        }
    except Exception as e:
        print(f"Error fetching user data for API: {e}")
        raise HTTPException(status_code=500, detail="Error fetching user data")

@app.post("/api/team/{team_id}/update")
async def update_team_data(team_id: int, request: TeamUpdateRequest):
    """
    Saves the new Pokémon UUID list for a specific team.
    """
    try:
        # Re-use your existing database function
        db.update_team(team_id, request.team_uuids)
        
        # Also set the active team if it's the one being edited
        db.set_active_team(request.user_id, team_id)

        return {"status": "success", "message": f"Team {team_id} updated."}
    except Exception as e:
        print(f"Error updating team for API: {e}")
        raise HTTPException(status_code=500, detail="Error updating team")

@app.get("/api/pokemon/{user_id}/{pokemon_uuid}")
async def get_pokemon_data(user_id: int, pokemon_uuid: str):
    """
    Fetches a single Pokémon's data for the editor.
    """
    try:
        pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
        if not pokemon:
            raise HTTPException(status_code=404, detail="Pokémon not found")

        species_data = SPECIES_BY_ID.get(pokemon.id)

        # --- NEW: Get the learnset ---
        learnset_data = get_species_learnset(pokemon.id)

        # --- NEW: Process learnset into a structured list ---
        # We do this on the backend to make it easy for JavaScript
        processed_learnset = []
        for move_id, methods in learnset_data.items():
            move_info = MOVE_BY_ID.get(move_id)
            if move_info:
                processed_learnset.append({
                    "id": move_id,
                    "name": move_info["name"],
                    "methods": methods # e.g., ["8L10", "8M"]
                })

        # Sort the learnset alphabetically
        processed_learnset.sort(key=lambda x: x["name"])

        return {
            "pokemon": jsonable_encoder(pokemon),
            "species": species_data,
            "learnset": processed_learnset,
            "all_items": ALL_ITEMS # Send the full item list
        }
    except Exception as e:
        print(f"Error fetching Pokémon data for API: {e}")
        raise HTTPException(status_code=500, detail="Error fetching Pokémon data")


@app.post("/api/pokemon/{pokemon_uuid}/update")
async def update_pokemon_data(pokemon_uuid: str, request: PokemonEditorUpdateRequest): # Use new model
    """
    Saves the updated Pokémon data back to the database after full server-side validation.
    """
    try:
        user_id = request.user_id
        
        # --- 1. FETCH (Get the trusted object from the DB) ---
        pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid) 
        if not pokemon:
            raise HTTPException(status_code=404, detail="Pokémon not found in collection")

        species_data = SPECIES_BY_ID.get(pokemon.id) 
        if not species_data:
            raise HTTPException(status_code=404, detail="Pokémon species data not found")

        # --- 2. VALIDATE (Check every single new value) ---
        
        # Validate Level (already handled by Pydantic model)
        new_level = request.level

        # Validate EVs
        new_evs = request.evs
        ev_total = sum(new_evs.values())
        if ev_total > 510:
            raise HTTPException(status_code=400, detail=f"EV total ({ev_total}) exceeds 510.")
        for stat_val in new_evs.values():
            if not 0 <= stat_val <= 252:
                raise HTTPException(status_code=400, detail="Invalid EV value. Must be 0-252.")

        # Validate IVs
        for stat_val in request.ivs.values():
            if not 0 <= stat_val <= 31:
                raise HTTPException(status_code=400, detail="Invalid IV value. Must be 0-31.")

        # Validate Nature
        if request.nature not in ALL_NATURES: 
            raise HTTPException(status_code=400, detail="Invalid nature selected.")

        # Validate Ability
        valid_abilities = list(species_data.get("abilities", {}).values())
        if request.ability not in valid_abilities:
            raise HTTPException(status_code=400, detail="Invalid ability for this Pokémon.")

        # Validate Item
        if request.item is not None and request.item not in ALL_ITEMS: 
            raise HTTPException(status_code=400, detail="Invalid item selected.")

        # Validate Moves
        learnset_data = get_species_learnset(pokemon.id)
        for move_id in request.moves:
            if move_id not in learnset_data:
                raise HTTPException(status_code=400, detail=f"Invalid move: {move_id} is not in learnset.")

        # --- 3. APPLY & SAVE (Update the trusted object) ---
        
        pokemon.level = new_level
        pokemon.nature = request.nature
        pokemon.ability = request.ability
        pokemon.item = request.item
        pokemon.tera_type = request.tera_type
        pokemon.moves = request.moves
        
        # Re-create the Stats objects
        pokemon.evs = Stats(hp=new_evs['hp'], atk=new_evs['atk'], def_=new_evs['def'], spa=new_evs['spa'], spd=new_evs['spd'], spe=new_evs['spe']) 
        pokemon.ivs = Stats(hp=request.ivs['hp'], atk=request.ivs['atk'], def_=request.ivs['def'], spa=request.ivs['spa'], spd=request.ivs['spd'], spe=request.ivs['spe']) 

        # Use your existing DB function to save it
        if db.update_pokemon_in_collection(user_id, pokemon): 
            return {"status": "success", "message": f"{pokemon.name} updated."}
        else:
            raise HTTPException(status_code=500, detail="Failed to update Pokémon in collection")
            
    except HTTPException as http_exc:
        # Re-raise HTTP exceptions directly
        raise http_exc
    except Exception as e:
        print(f"Error updating Pokémon for API: {e}")
        traceback.print_exc() 
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")


@app.get("/api/user/{user_id}/profile")
async def get_user_profile_data(user_id: int):
    """
    Fetches all necessary data for the main profile page.
    """
    try:
        # --- START OF MODIFICATION ---

        # 1. Fetch user info (for their name and new favorite UUID)
        user_info = db.get_user_by_id(user_id) #

        if not user_info:
            db.add_user(user_id, "", "", "") #
            user_info = db.get_user_by_id(user_id) 
            stats = db.get_user_stats(user_id) 
        else:
            stats = db.get_user_stats(user_id) #

        # Find the favorite_pokemon_uuid. 
        # !IMPORTANT: You must find the correct index for 'favorite_pokemon_uuid'
        # based on your table's column order from 'SELECT *'. I will assume it's index 15.
        # Please double-check this index in your database.
        COL_INDEX_FAVORITE_UUID = 15 
        favorite_uuid = user_info[COL_INDEX_FAVORITE_UUID] if user_info and user_info[COL_INDEX_FAVORITE_UUID] else None

        theme_type = None
        animated_sprite = None

        if favorite_uuid:
            pokemon = db.get_pokemon_from_collection(user_id, favorite_uuid)
            if pokemon:
                species_data = SPECIES_BY_ID.get(pokemon.id, {})
                # Get the Gen 5 animated sprite URL [cite: 89-91]
                animated_sprite = species_data.get('versions', {}).get('generation-v', {}).get('black-white', {}).get('animated', {}).get('front_default')

        user_first_name = user_info[2] if user_info and user_info[2] else "Trainer" #
        # --- END OF MODIFICATION ---

        shiny_passes = db.get_shiny_pass_count(user_id) #
        legendary_passes = db.get_legendary_pass_count(user_id) #
        clash_coins = db.get_clash_coin_count(user_id) #

        active_team_data = db.get_active_team(user_id) #
        team_pokemon = []

        if active_team_data:
            team_uuids = active_team_data[3] if active_team_data[3] else [] #
            collection = db.get_collection(user_id) #
            pokemon_map = {p.pokemon_uuid: p for p in collection} #

            for uuid in team_uuids:
                if uuid in pokemon_map:
                    pokemon = pokemon_map[uuid]
                    species_data = SPECIES_BY_ID.get(pokemon.id)
                    team_pokemon.append({
                        "name": pokemon.name,
                        "num": species_data.get("num") if species_data else 0 
                    })

        if not stats:
             raise HTTPException(status_code=500, detail="Failed to create/fetch user stats.")


        elo, wins, losses, draws = stats #

        rank_details = get_rank_details(elo) #

        return {
            "user_first_name": user_first_name, 
            "elo": elo,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "rank_name": rank_details['name'],
            "shiny_passes": shiny_passes,
            "legendary_passes": legendary_passes,
            "clash_coins": clash_coins,
            "active_team": team_pokemon,
            "animated_sprite_url": animated_sprite
        }
    except Exception as e:
        print(f"Error fetching profile data for API: {e}")
        raise HTTPException(status_code=500, detail="Error fetching user data")

@app.get("/api/user/{user_id}/trainer-card.png")
async def get_user_trainer_card_image(user_id: int):
    user_info = db.get_user_by_id(user_id)
    stats = db.get_user_stats(user_id)
    prefs = db.get_user_card_prefs(user_id)
    if not user_info or not stats or not prefs:
        raise HTTPException(status_code=404, detail="Trainer card not found")

    user_name = user_info[2] if len(user_info) > 2 and user_info[2] else "Trainer"
    elo, wins, losses, _ = stats
    card_template, trainer_sprite, font_color = prefs
    card_image = await create_trainer_card_image(
        user_name,
        int(elo or 1000),
        int(wins or 0),
        int(losses or 0),
        card_template,
        trainer_sprite,
        font_color,
    )
    if not card_image:
        raise HTTPException(status_code=404, detail="Trainer card image unavailable")
    return Response(
        content=card_image.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )

@app.get("/card/{user_id}")
async def trainer_card_link_preview(user_id: int):
    user_info = db.get_user_by_id(user_id)
    stats = db.get_user_stats(user_id)
    if not user_info or not stats:
        raise HTTPException(status_code=404, detail="Trainer card not found")

    user_name = user_info[2] if len(user_info) > 2 and user_info[2] else "Trainer"
    elo, wins, losses, draws = stats
    rank_details = get_rank_details(int(elo or 1000))
    origin = RENDER_URL or ""
    image_url = f"{origin}/api/user/{user_id}/trainer-card.png" if origin else f"/api/user/{user_id}/trainer-card.png"
    profile_url = f"{origin}/profile.html?user_id={user_id}" if origin else f"/profile.html?user_id={user_id}"
    title = html_escape(f"{user_name}'s PokeClash Trainer Card")
    description = html_escape(
        f"{rank_details['name']} | Elo {int(elo or 1000)} | {int(wins or 0)}W-{int(losses or 0)}L-{int(draws or 0)}D"
    )
    safe_image_url = html_escape(image_url)
    safe_profile_url = html_escape(profile_url)
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta property="og:type" content="profile">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:image" content="{safe_image_url}">
  <meta property="og:image:type" content="image/png">
  <meta property="twitter:card" content="summary_large_image">
  <meta property="twitter:title" content="{title}">
  <meta property="twitter:description" content="{description}">
  <meta property="twitter:image" content="{safe_image_url}">
  <meta http-equiv="refresh" content="0; url={safe_profile_url}">
</head>
<body>
  <a href="{safe_profile_url}">{title}</a>
</body>
</html>"""
    return Response(content=body, media_type="text/html")

@app.get("/api/user/{user_id}/pfp")
async def get_user_profile_picture(user_id: int):
    """
    Fetches the user's profile picture using the bot's API
    and returns it as an image file, bypassing CORS.
    """
    try:
        # 1. Get the user's profile photos from Telegram
        user_photos = await bot.get_user_profile_photos(user_id, limit=1)
        
        if not user_photos or not user_photos.photos:
            # User has no photo, return a 404
            raise HTTPException(status_code=404, detail="User has no profile picture.")

        # 2. Get the file_id of the smallest photo
        file_id = user_photos.photos[0][0].file_id # [0] is the first photo, [0] is the smallest size
        
        # 3. Get the file path from Telegram
        file_info = await bot.get_file(file_id)
        file_path = file_info.file_path

        # 4. Construct the public download URL
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        
        # 5. Download the image bytes using aiohttp (which is already in your project)
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=500, detail="Failed to download photo from Telegram.")
                
                image_bytes = await resp.read()
                
                # 6. Return the image bytes directly with the correct content type
                return Response(content=image_bytes, media_type="image/jpeg")

    except Exception as e:
        # If anything fails (e.g., user not found, 403 error), return a 404
        # This will trigger the 'onerror' in the browser.
        print(f"Error fetching PFP for user {user_id}: {e}")
        raise HTTPException(status_code=404, detail="Error fetching profile picture.")


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBSITE_DIR = os.path.join(PROJECT_ROOT, "website") 
if os.path.exists(WEBSITE_DIR):
    app.mount("/", StaticFiles(directory=WEBSITE_DIR, html=True), name="static")
else:
    print(f"WARNING: Website directory not found at {WEBSITE_DIR}")

# ====================================================================
# --- END NEW API SECTION ---
# ====================================================================

async def scheduled_db_backup(bot: AsyncTeleBot):
    """
    Runs every 24 hours to backup the database and upload it to the backup channel.
    """
    backup_chat_id = os.getenv("BACKUP_CHAT_ID")
    
    if not backup_chat_id:
        logging.warning("⚠️ BACKUP_CHAT_ID not set in .env. Automatic backups disabled.")
        return

    while True:
        # Wait for 24 hours (86400 seconds) before the next backup
        # You can change this to run immediately on startup by moving this sleep to the end of the loop
        await asyncio.sleep(86400) 

        logging.info("⏳ Starting scheduled daily database backup...")
        
        db_host = os.getenv("DB_HOST", "localhost")
        db_name = os.getenv("DB_NAME")
        db_user = os.getenv("DB_USER")
        db_pass = os.getenv("DB_PASS")
        db_port = os.getenv("DB_PORT", "5432")

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"daily_backup_{db_name}_{timestamp}.sql"

        try:
            env = os.environ.copy()
            env["PGPASSWORD"] = db_pass

            # Create the dump
            command = [
                "pg_dump",
                "-h", db_host,
                "-p", db_port,
                "-U", db_user,
                "-F", "c",
                "-b",
                "-f", filename,
                db_name
            ]

            process = await asyncio.create_subprocess_exec(
                *command,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            _, stderr = await process.communicate()

            if process.returncode != 0:
                logging.error(f"❌ Scheduled backup failed: {stderr.decode()}")
                await bot.send_message(
                    backup_chat_id, 
                    f"❌ **Daily Backup Failed!**\n\nError: `{stderr.decode()}`", 
                    parse_mode="Markdown"
                )
            else:
                # Upload the file
                with open(filename, 'rb') as backup_file:
                    await bot.send_document(
                        chat_id=backup_chat_id,
                        document=backup_file,
                        caption=f"📦 **Daily Database Backup**\n📅 {timestamp}\n💽 DB: {db_name}",
                        parse_mode="Markdown"
                    )
                logging.info("✅ Scheduled backup uploaded successfully.")

        except Exception as e:
            logging.error(f"❌ Exception during scheduled backup: {e}")
            try:
                await bot.send_message(backup_chat_id, f"❌ **Backup Error:** `{str(e)}`")
            except Exception:
                pass # If we can't even send the error message, just log it.
        
        finally:
            if os.path.exists(filename):
                os.remove(filename)

# --- Background Task for Overall Battle Timeout ---
async def monitor_active_battles(bot: AsyncTeleBot):
    """
    A background task that runs forever to clean up expired or finished battles.
    """
    while True:
        await asyncio.sleep(30) # Check once every 30 sec
        
        for chat_id in list(active_battles.keys()):
            battles_to_remove = []
            for battle in active_battles.get(chat_id, []):
                if battle.state == 'finished':
                    battles_to_remove.append(battle)
                    print(f"Cleaned up zombie 'finished' battle in chat {chat_id}")
                    continue

                if datetime.now() - battle.start_time > timedelta(minutes=15):
                    try:
                        await bot.edit_message_caption(
                            caption=f"⌛ Battle Timed Out!\n\nThe match was automatically ended after 10 minutes.",
                            chat_id=battle.chat_id,
                            message_id=battle.message_id,
                            reply_markup=None
                        )
                    except Exception as e:
                        print(f"Could not edit timed-out battle message: {e}")
                    finally:
                        battles_to_remove.append(battle)
                        print(f"Cleaned up expired battle in chat {chat_id}")
            
            if battles_to_remove:
                active_battles[chat_id] = [b for b in active_battles[chat_id] if b not in battles_to_remove]
            
            if not active_battles.get(chat_id):
                del active_battles[chat_id]

async def async_main():
    """
    Registers all handlers, starts background tasks, and runs the bot's polling.
    """
    # Register all your handlers as before
    register_command_handlers(bot)
    register_showdown_challenge_handlers(bot)
    register_callback_handlers(bot)
    register_battle_handlers(bot)
    register_dex_handlers(bot)

    logging.info(f'Bot is starting as @{BOT_USERNAME}...')
    
    # Start the background task for monitoring battles
    asyncio.create_task(monitor_active_battles(bot))
    asyncio.create_task(scheduled_db_backup(bot))
    
    # Start the bot's main polling loop
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)), log_level="info")
    server = uvicorn.Server(config)
    
    bot_task = asyncio.create_task(bot.polling(none_stop=True, interval=0, skip_pending=True))
    server_task = asyncio.create_task(server.serve())
    
    # Run both tasks concurrently
    await asyncio.gather(bot_task, server_task)

def main():
    """
    The main entry point that runs the asynchronous application.
    """
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nCaught KeyboardInterrupt, shutting down...")
    finally:
        print("Bot stopped gracefully.")
