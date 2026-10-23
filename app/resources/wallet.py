"""Expose wallet information through the authenticated Campus API."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.managers.points import get_wallet
from app.managers.security import get_current_user
from app.models.user import User
from app.schemas.response.wallet import WalletResponse

router = APIRouter(prefix="/wallet", tags=["Wallet"])


@router.get("/me")
async def get_my_wallet(
    current_user: Annotated[User, Depends(get_current_user)],
) -> WalletResponse:
    """Derive the wallet owner from authentication, not client input."""
    return await get_wallet(current_user.id)
