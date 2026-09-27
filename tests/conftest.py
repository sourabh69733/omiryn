import os

import dotenv

os.environ["DATABASE_URL"] = os.getenv("OMIRYN_TEST_DATABASE_URL", "sqlite:///./data/omiryn_test.db")

# Tests run on their own settings, never on the developer's local .env. The app and the eval
# scripts call load_dotenv() when imported, so it becomes a no-op before any of them load.
dotenv.load_dotenv = lambda *args, **kwargs: False
