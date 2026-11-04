import os

import dotenv

os.environ["DATABASE_URL"] = os.getenv("OMIRYN_TEST_DATABASE_URL", "sqlite:///./data/omiryn_test.db")

# Replies start at once unless a test is about the wait for more messages.
os.environ["CHAT_BURST_QUIET_SECONDS"] = "0"

# Off by default in the app; the tests of those messages need them on.
os.environ["PROACTIVE_MESSAGING_ENABLED"] = "true"

# Tests run on their own settings, never on the developer's local .env. The app and the eval
# scripts call load_dotenv() when imported, so it becomes a no-op before any of them load.
dotenv.load_dotenv = lambda *args, **kwargs: False


def pytest_sessionstart(session) -> None:
    # The test database file outlives runs; add columns from newer code before any test uses it.
    from storage import init_db

    init_db()
