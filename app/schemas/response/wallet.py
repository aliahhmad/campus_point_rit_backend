"""Describe the available points returned by the wallet APIs."""

from pydantic import BaseModel, Field


class WalletResponse(BaseModel):
    """Identify the wallet owner and their spendable points."""

    user_id: int = Field(gt=0)
    available_points: int = Field(ge=0)
