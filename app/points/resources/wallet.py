"""Internal endpoints for provisioning Points wallets."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.points.database import get_database
from app.points.managers.wallet import get_wallet, initialize_wallet
from app.points.schemas.wallet import WalletInitializationResponse
from app.points.security import require_service_token
from app.schemas.response.wallet import WalletResponse

router = APIRouter(
    prefix="/internal/wallets",
    tags=["Internal wallets"],
    dependencies=[Depends(require_service_token)],
)


@router.get("/{user_id}")
async def read_wallet(
    user_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    session: Annotated[AsyncSession, Depends(get_database)],
) -> WalletResponse:
    """Return the balance to an authenticated service caller."""
    wallet = await get_wallet(user_id, session)
    return WalletResponse(
        user_id=wallet.user_id, available_points=wallet.available_points
    )


@router.put("/{user_id}/initialize")
async def initialize(
    user_id: Annotated[int, Path(gt=0)],
    session: Annotated[AsyncSession, Depends(get_database, scope="function")],
) -> WalletInitializationResponse:
    """Commit the wallet and one opening grant before acknowledging success."""
    wallet, granted = await initialize_wallet(user_id, session)
    return WalletInitializationResponse(
        user_id=wallet.user_id,
        available_points=wallet.available_points,
        reputation=wallet.reputation,
        opening_grant_issued=granted,
    )
