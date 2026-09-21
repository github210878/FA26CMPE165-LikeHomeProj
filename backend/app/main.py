from fastapi import FastAPI
from app.config.config import Config

from app.routers.user_router import router as user_router

app = FastAPI(title=Config.APP_NAME, version=Config.APP_VERSION)


app.include_router(user_router)
