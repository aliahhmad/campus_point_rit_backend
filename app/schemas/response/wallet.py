"""Describe the points and reputation returned by the wallet APIs."""

from pydantic import BaseModel, Field


class WalletResponse(BaseModel):
    """Identify the wallet owner, spendable points, and reputation."""

    user_id: int = Field(gt=0)
    available_points: int = Field(ge=0)
    reputation: int = Field(ge=0)
