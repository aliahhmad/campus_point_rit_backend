"""Approve request content when it contains no configured abusive words."""

import re

from app.config.settings import get_settings
from app.logs import logger
from app.models.enums import ModerationStatus


def auto_moderate_request(title: str, description: str) -> ModerationStatus:
    """Check both fields for literal whole words, ignoring case.

    Matches hide content; failures leave it pending. An empty blocklist approves
    all content. This checks new submissions; it does not change existing ones.
    """
    try:
        title = title.casefold()
        description = description.casefold()
        blocked_words = get_settings().moderation_blocked_words.split(",")

        for configured_word in blocked_words:
            word = configured_word.strip().casefold()
            if not word:
                continue

            # Match the whole word, allowing punctuation around it.
            pattern = r"\b" + re.escape(word) + r"\b"
            if re.search(pattern, title) or re.search(pattern, description):
                return ModerationStatus.hidden

    except Exception:  # noqa: BLE001 - Failed checks must leave content unpublished.
        logger.exception("Request moderation failed; leaving request pending")
        return ModerationStatus.pending

    return ModerationStatus.visible
