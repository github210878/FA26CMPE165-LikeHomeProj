from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config.config import Config

from app.routers.user_router import router as user_router
from app.routers.hotel_router import router as hotel_router
from app.routers.booking_router import router as booking_router

app = FastAPI(title=Config.APP_NAME, version=Config.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


app.include_router(user_router)
app.include_router(hotel_router)
app.include_router(booking_router)
