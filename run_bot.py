from dotenv import load_dotenv
import os

load_dotenv()

SPORTSBOOK_API_KEY = os.getenv("SPORTSBOOK_API_KEY")
print("API KEY FOUND:", bool(SPORTSBOOK_API_KEY))
from bot.main import main

if __name__ == "__main__":
    main()

