"""Configure Points tests without importing the Campus test database hooks."""

import os

# Tests mock the database; this password is only needed to load the settings.
os.environ.setdefault("POINTS_DB_PASSWORD", "points-test-unused-password")
