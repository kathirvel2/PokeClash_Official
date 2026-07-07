# ./reset_database.py
import os
import psycopg2
import sys
from dotenv import load_dotenv

def reset_database():
    """
    Connects to the database and resets all user *progress*, but
    does NOT delete the users themselves.
    - TRUNCATES (deletes all data from) 'teams' and 'collections'.
    - UPDATES 'users' table to reset all stats, items, and teams to default.
    """
    # --- Step 1: Load the correct .env file ---
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    env_mode = os.getenv('ENV_MODE', 'development')
    
    if env_mode == 'production':
        print("--- TARGETING PRODUCTION DATABASE ---")
        dotenv_path = os.path.join(PROJECT_ROOT, '.env.production')
    else:
        print("--- TARGETING DEVELOPMENT DATABASE ---")
        dotenv_path = os.path.join(PROJECT_ROOT, '.env')
        
    if not os.path.exists(dotenv_path):
        print(f"ERROR: Environment file not found at {dotenv_path}")
        sys.exit(1)
        
    load_dotenv(dotenv_path=dotenv_path)

    # --- Step 2: Get DB credentials ---
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")

    # --- Step 3: DANGEROUS ACTION - REQUIRE CONFIRMATION ---
    print("\n⚠️ WARNING! ⚠️")
    print(f"You are about to RESET ALL USER PROGRESS in the '{db_name}' database.")
    print("\nThis will:")
    print("  1. DELETE ALL DATA from the 'teams' and 'collections' tables.")
    print("  2. RESET all user stats (Elo, wins, coins, slots) in the 'users' table to default.")
    print("\nUser accounts and names will NOT be deleted.")
    print("This action is irreversible.")
    
    confirmation = input('Type "YES" to confirm: ')
    if confirmation != "YES":
        print("Aborted. No changes were made.")
        return

    # --- Step 4: Execute the deletion and reset ---
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            dbname=db_name,
            user=db_user,
            password=os.getenv("DB_PASS"),
            port=os.getenv("DB_PORT", "5432"),
            sslmode=os.getenv("DB_SSLMODE"),
            sslrootcert=os.getenv("DB_SSLCERT")
        )
        cursor = conn.cursor()
        
        print("\nConnecting to the database...")
        
        # 1. Truncate the 'teams' and 'collections' tables
        print("Clearing 'teams' and 'collections' tables...")
        cursor.execute("TRUNCATE TABLE teams, collections RESTART IDENTITY CASCADE;")
        
        # 2. Update the 'users' table to reset progress
        print("Resetting all user progress in 'users' table...")
        update_query = """
            UPDATE users SET
                active_team_id = NULL,
                battle_mode = 'turn-based',
                mega_enabled = TRUE,
                gmax_enabled = TRUE,
                elo_score = 1000,
                wins = 0,
                losses = 0,
                draws = 0,
                ranking_enabled = FALSE,
                card_template = 'normalcard/card1.png',
                trainer_sprite = 'ethan.png',
                card_font_color = 'white',
                legendary_mode = FALSE,
                non_legendary_mode = FALSE,
                sleep_clause_enabled = TRUE,
                random_battle_generation = 0,
                shiny_pass_count = 1,
                legendary_pass_count = 0,
                clash_coins = 1000,
                favorite_pokemon_uuid = NULL,
                max_pokemon_slots = 12;
        """
        cursor.execute(update_query)
        
        conn.commit()
        cursor.close()
        print("\n✅ Success! 'teams' and 'collections' tables cleared.")
        print("✅ All user progress has been reset to default.")
        
    except psycopg2.Error as e:
        print(f"\n❌ An error occurred: {e}")
        if conn:
            conn.rollback() # Rollback any partial changes on error
    finally:
        if conn is not None:
            conn.close()

if __name__ == '__main__':
    reset_database()
