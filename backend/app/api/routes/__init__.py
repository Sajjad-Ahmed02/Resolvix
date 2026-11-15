from fastapi import APIRouter

from app.api.routes import admin, auth, conversations, health, orders


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(conversations.router)
api_router.include_router(orders.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]
