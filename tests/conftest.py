import os


os.environ["DATABASE_URL"] = os.getenv("OMIRYN_TEST_DATABASE_URL", "sqlite:///./data/omiryn_test.db")
