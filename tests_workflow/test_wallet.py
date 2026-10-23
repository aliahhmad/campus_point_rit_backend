"""Verify that the profile wallet endpoint reflects actual request holds."""

import pytest
from fastapi import status

from app.config.settings import get_settings
from tests_workflow.conftest import Workflow


@pytest.mark.asyncio
async def test_profile_points_after_request(workflow: Workflow) -> None:
    """Read the real Points balance through Campus before and after creation."""
    root = get_settings().api_root
    before = await workflow.client.get(root + "/wallet/me")
    assert before.status_code == status.HTTP_200_OK
    assert before.json() == {
        "user_id": 1,
        "available_points": 100,
        "reputation": 0,
    }
    created = await workflow.client.post(
        root + "/requests",
        json={
            "location_id": 1,
            "title": "Library crowding",
            "description": "Are there any empty study tables?",
        },
        headers={"Idempotency-Key": "wallet-profile-test"},
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    after = await workflow.client.get(root + "/wallet/me")
    assert after.status_code == status.HTTP_200_OK
    assert after.json() == {
        "user_id": 1,
        "available_points": 95,
        "reputation": 0,
    }
