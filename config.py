import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dire-pro-max-dev-key")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg:///dire_pro_max"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
