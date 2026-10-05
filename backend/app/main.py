from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.config import Config

from app.routers.user_router import router as user_router
from app.routers.hotel_router import router as hotel_router
from app.routers.booking_router import router as booking_router
from app.routers.partner_router import router as partner_router

app = FastAPI(title=Config.APP_NAME, version=Config.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(user_router)
app.include_router(hotel_router)
app.include_router(booking_router)
app.include_router(partner_router)
