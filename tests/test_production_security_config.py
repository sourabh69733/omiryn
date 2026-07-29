import base64
import os
import unittest
from unittest.mock import patch

from security.auth import (
    ProductionSecurityConfigError,
    production_runtime_enabled,
    validate_production_security_config,
)


def _valid_master_key() -> str:
    return base64.urlsafe_b64encode(b"0" * 32).decode("ascii")


class ProductionSecurityConfigTest(unittest.TestCase):
    def test_local_runtime_does_not_require_production_secrets(self) -> None:
        with patch.dict(os.environ, {"APP_ENV": "local", "AUTH_REQUIRED": "false"}, clear=True):
            validate_production_security_config()
            self.assertFalse(production_runtime_enabled())

    def test_production_runtime_accepts_secure_baseline(self) -> None:
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "AUTH_REQUIRED": "true",
                "AUTH_PROVIDER": "supabase",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "anon-public-key",
                "ENCRYPTION_MASTER_KEY": _valid_master_key(),
                "ADMIN_EMAILS": "admin@example.com",
                "ADMIN_ALLOW_UNAUTHENTICATED_DEV": "false",
            },
            clear=True,
        ):
            validate_production_security_config()
            self.assertTrue(production_runtime_enabled())

    def test_production_runtime_rejects_insecure_auth(self) -> None:
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "AUTH_REQUIRED": "false",
                "AUTH_PROVIDER": "none",
                "SUPABASE_URL": "",
                "SUPABASE_ANON_KEY": "",
                "ENCRYPTION_MASTER_KEY": "",
                "ADMIN_ALLOW_UNAUTHENTICATED_DEV": "true",
                "ADMIN_EMAILS": "",
                "ADMIN_USER_IDS": "",
            },
            clear=True,
        ):
            with self.assertRaises(ProductionSecurityConfigError) as error:
                validate_production_security_config()

        message = str(error.exception)
        self.assertIn("AUTH_REQUIRED must be true", message)
        self.assertIn("AUTH_PROVIDER must be supabase", message)
        self.assertIn("ADMIN_ALLOW_UNAUTHENTICATED_DEV must be false", message)
        self.assertIn("ADMIN_EMAILS or ADMIN_USER_IDS", message)

    def test_cloud_run_environment_is_treated_as_production(self) -> None:
        with patch.dict(
            os.environ,
            {
                "K_SERVICE": "omiryn-api",
                "AUTH_REQUIRED": "false",
            },
            clear=True,
        ):
            self.assertTrue(production_runtime_enabled())
            with self.assertRaises(ProductionSecurityConfigError):
                validate_production_security_config()

