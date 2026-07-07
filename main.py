import os
from dotenv import load_dotenv

# --- STEP 1: LOAD ENV VARS *FIRST* ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Ensure that ENV_MODE is set BEFORE load_dotenv() checks it
if os.getenv('ENV_MODE') == 'production': 
    # This block executes if you set ENV_MODE in systemd
    dotenv_path = os.path.join(PROJECT_ROOT, '.env.production')
else:
    # This block executes if ENV_MODE is unset or anything else
    dotenv_path = os.path.join(PROJECT_ROOT, '.env')

load_dotenv(dotenv_path=dotenv_path) 
# --- The entire application relies on environment variables being set here ---

from bot.main import main

if __name__ == '__main__':
    main()
