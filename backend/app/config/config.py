import os
from dotenv import load_dotenv

load_dotenv()


class Config:

    # App config
    APP_NAME = "LikeHome Backend"
    APP_VERSION = "1.0.0"

    # Database config
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", 3306))
    DB_NAME = os.getenv("DB_NAME", "likehome_db")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_USER = os.getenv("DB_USER", "root")
    DB_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    # External API config
    EXTERNAL_API_URL = os.getenv("EXTERNAL_API_URL")
    API_KEY = os.getenv("API_KEY")
