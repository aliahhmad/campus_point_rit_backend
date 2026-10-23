"""Register Points routes here, separately from Campus routes."""

from fastapi import APIRouter

from app.points.resources import health, transactions, wallet

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(wallet.router)
api_router.include_router(transactions.router)
