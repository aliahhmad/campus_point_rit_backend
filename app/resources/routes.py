"""Include all the other routes into one router."""

from fastapi import APIRouter

from app.config.settings import get_settings
from app.resources import (
    acceptance,
    api_key,
    auth,
    campus_request,
    campus_response,
    heartbeat,
    home,
    location,
    transactions,
    user,
    wallet,
)

api_router = APIRouter(prefix=get_settings().api_root)

api_router.include_router(user.router)
api_router.include_router(wallet.router)
api_router.include_router(auth.router)
api_router.include_router(api_key.router)
api_router.include_router(campus_request.router)
api_router.include_router(campus_response.router)
api_router.include_router(acceptance.router)
api_router.include_router(location.router)
api_router.include_router(transactions.router)
api_router.include_router(heartbeat.router)

if not get_settings().no_root_route:
    api_router.include_router(home.router)
