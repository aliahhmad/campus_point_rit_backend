"""Check automatic approval and the status saved during request creation."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import asyncpg
import pytest

from app.config.settings import get_settings
from app.managers.moderation import auto_moderate_request
from app.managers.request_participant import insert_request
from app.models.enums import ModerationStatus
from app.transactions.schemas import RequestPreparation


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        ("Library crowding", "Are there seats?", ModerationStatus.visible),
        ("SHIT!", "Are there seats?", ModerationStatus.hidden),
        ("Library crowding", "This is shit.", ModerationStatus.hidden),
        ("Library crowding", "A fucking mess", ModerationStatus.hidden),
        ("Library crowding", "You are an asshole", ModerationStatus.hidden),
        ("Class assignment", "Please assist me", ModerationStatus.visible),
        ("A scunthorpe visit", "A classic", ModerationStatus.visible),
        ("Library crowding", "shitake mushrooms", ModerationStatus.visible),
        ("Library crowding", "Stop\nshit\nnow", ModerationStatus.hidden),
    ],
)
def test_auto_moderation(
    monkeypatch: pytest.MonkeyPatch,
    title: str,
    description: str,
    expected: ModerationStatus,
) -> None:
    """Check both fields, case, punctuation, and innocent longer words."""
    monkeypatch.setattr(
        get_settings(), "moderation_blocked_words", "shit,fucking,asshole,cunt"
    )
    assert auto_moderate_request(title, description) is expected


@pytest.mark.parametrize(
    ("words", "text", "expected"),
    [
        ("  ShIt , , ", "SHIT!", ModerationStatus.hidden),
        ("", "shit", ModerationStatus.visible),
        (" , , ", "shit", ModerationStatus.visible),
        ("customword", "customword", ModerationStatus.hidden),
        ("customword", "shit", ModerationStatus.visible),
        ("bad.word", "badXword", ModerationStatus.visible),
        ("bad.word", "bad.word!", ModerationStatus.hidden),
    ],
)
def test_configured_blocklist(
    monkeypatch: pytest.MonkeyPatch,
    words: str,
    text: str,
    expected: ModerationStatus,
) -> None:
    """Respect custom lists, blank entries, and literal regex characters."""
    monkeypatch.setattr(get_settings(), "moderation_blocked_words", words)
    assert auto_moderate_request("Library", text) is expected


@pytest.mark.parametrize(
    ("target", "error"),
    [
        ("get_settings", OSError("Moderation unavailable")),
        ("get_settings", TimeoutError("Moderation timed out")),
        ("re.search", RuntimeError("Moderation check failed")),
    ],
)
def test_moderation_failure_returns_pending(
    monkeypatch: pytest.MonkeyPatch, target: str, error: Exception
) -> None:
    """A failed check leaves content unpublished instead of approving it."""
    monkeypatch.setattr(get_settings(), "moderation_blocked_words", "shit")
    monkeypatch.setattr(
        f"app.managers.moderation.{target}", Mock(side_effect=error)
    )
    assert auto_moderate_request("Library", "Are there seats?") is (
        ModerationStatus.pending
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("moderation_fails", [False, True])
@pytest.mark.parametrize(
    ("description", "expected"),
    [("Are there seats?", "visible"), ("This is SHIT!", "hidden")],
)
async def test_creation_saves_moderation_status(
    monkeypatch: pytest.MonkeyPatch,
    description: str,
    expected: str,
    *,
    moderation_fails: bool,
) -> None:
    """The actual insertion path persists the server's moderation decision."""
    monkeypatch.setattr(get_settings(), "moderation_blocked_words", "shit")
    if moderation_fails:
        monkeypatch.setattr(
            "app.managers.moderation.get_settings", Mock(side_effect=OSError)
        )
        expected = "pending"
    conn = AsyncMock(spec=asyncpg.Connection)
    conn.fetchval.return_value = 1
    payload = RequestPreparation(
        owner_id=1,
        request_id=1,
        location_id=1,
        title="Library crowding",
        description=description,
    )
    await insert_request(conn, uuid4(), payload)
    conn.execute.assert_awaited_once_with(
        "INSERT INTO requests "
        "(id,requester_id,location_id,title,description,moderation_status) "
        "VALUES ($1,$2,$3,$4,$5,$6)",
        1,
        1,
        1,
        "Library crowding",
        description,
        expected,
    )
