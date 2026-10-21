"""Initialize each wallet and opening grant in one local transaction."""

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.points.models import PointsTransaction, Wallet
from app.points.models.enums import PointsTransactionType

OPENING_GRANT = 100


async def initialize_wallet(
    user_id: int,
    session: AsyncSession,
) -> tuple[Wallet, bool]:
    """Issue a grant once, locking the wallet in the caller's transaction."""
    await session.execute(
        insert(Wallet)
        .values(user_id=user_id)
        .on_conflict_do_nothing(index_elements=[Wallet.user_id]),
    )
    result = await session.execute(
        select(Wallet).where(Wallet.user_id == user_id).with_for_update(),
    )
    wallet = result.scalar_one()
    grant = await session.scalar(
        select(PointsTransaction.id).where(
            PointsTransaction.user_id == user_id,
            PointsTransaction.type == PointsTransactionType.opening_grant,
        ),
    )
    granted = grant is None
    if granted:
        wallet.available_points += OPENING_GRANT
        session.add(
            PointsTransaction(
                operation_id=uuid5(
                    NAMESPACE_URL,
                    f"campuspoint:opening-grant:{user_id}",
                ),
                user_id=user_id,
                type=PointsTransactionType.opening_grant,
                amount=OPENING_GRANT,
            ),
        )
        await session.flush()
    return wallet, granted
