"""Check real request visibility, filtering, and location selection."""

import pytest
from fastapi import status

from app.config.settings import get_settings
from app.managers.security import get_current_user
from app.models.user import User
from app.transactions.postgres import connection
from tests_workflow.conftest import Workflow

pytestmark = pytest.mark.asyncio
ROOT = get_settings().api_root


async def test_request_feed(workflow: Workflow) -> None:
    """Only completed creations appear, with moderation enforced per owner."""
    own = await workflow.client.post(
        ROOT + "/requests",
        json={
            "title": "My question",
            "description": "Tables?",
            "location_id": 1,
        },
        headers={"Idempotency-Key": "feed-own"},
    )
    assert own.status_code == status.HTTP_201_CREATED
    own_id = own.json()["request"]["id"]

    async def other_user() -> User:
        return User(id=2)

    owner_dependency = workflow.campus.dependency_overrides[get_current_user]
    workflow.campus.dependency_overrides[get_current_user] = other_user
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "INSERT INTO locations (id,name,building_code)"
            " VALUES (2,'Gym','GYM')"
        )
    others = []
    for kind in ("visible", "pending", "hidden", "unconfirmed"):
        created = await workflow.client.post(
            ROOT + "/requests",
            json={
                "title": "Library 100% quiet" if kind == "visible" else kind,
                "description": "This is SHIT!"
                if kind == "pending"
                else "Is it busy?",
                "location_id": 2,
            },
            headers={"Idempotency-Key": "feed-" + kind},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        others.append(created.json())
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "UPDATE requests SET moderation_status='visible',"
            "status='under_review' WHERE id=$1",
            others[0]["request"]["id"],
        )
        await conn.execute(
            "UPDATE requests SET moderation_status='hidden' WHERE id=$1",
            others[2]["request"]["id"],
        )
        await conn.execute(
            "UPDATE requests SET moderation_status='visible' WHERE id=$1",
            others[3]["request"]["id"],
        )
        await conn.execute(
            "UPDATE distributed_transactions SET state='commit_decided'"
            " WHERE id=$1",
            others[3]["operation_id"],
        )
    workflow.campus.dependency_overrides[get_current_user] = owner_dependency
    response = await workflow.client.get(ROOT + "/requests")
    assert response.status_code == status.HTTP_200_OK, response.text
    items = response.json()["items"]
    assert [item["id"] for item in items] == [
        others[0]["request"]["id"],
        own_id,
    ]
    assert items[0]["location_name"] == "Gym"
    assert items[1]["moderation_status"] == "visible"
    for query in ("search=100%25", "location_id=2", "status=under_review"):
        filtered = await workflow.client.get(ROOT + "/requests?" + query)
        assert [item["id"] for item in filtered.json()["items"]] == [
            others[0]["request"]["id"]
        ]
    mine = await workflow.client.get(ROOT + "/requests?mine=true")
    assert [item["id"] for item in mine.json()["items"]] == [own_id]
    first = await workflow.client.get(ROOT + "/requests?size=1")
    second = await workflow.client.get(ROOT + "/requests?size=1&page=2")
    assert first.json()["has_more"] is True
    assert second.json()["has_more"] is False
    assert second.json()["items"][0]["id"] == own_id
    empty = await workflow.client.get(ROOT + "/requests?search=missing")
    assert empty.json()["items"] == []
    workflow.campus.dependency_overrides[get_current_user] = other_user
    other_feed = await workflow.client.get(ROOT + "/requests")
    assert {item["id"] for item in other_feed.json()["items"]} == {
        entry["request"]["id"] for entry in others[:3]
    }


async def test_location_dropdown(workflow: Workflow) -> None:
    """Exclude inactive locations but keep a confirmed request's old label."""
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "INSERT INTO locations (id,name,building_code,is_active) VALUES"
            " (2,'Closed','OFF',false),(3,'Gym','GYM',true)"
        )
    response = await workflow.client.get(ROOT + "/locations")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == [
        {"id": 3, "name": "Gym", "building_code": "GYM"},
        {"id": 1, "name": "Library", "building_code": "LIB"},
    ]
