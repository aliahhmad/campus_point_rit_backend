"""Describe the result of wallet initialization."""

from pydantic import BaseModel


class WalletInitializationResponse(BaseModel):
    """Return the current balance and whether this call issued the grant."""

    user_id: int
    available_points: int
    reputation: int
    opening_grant_issued: bool
