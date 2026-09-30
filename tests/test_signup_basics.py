"""One-screen signup (name + 18+) and a location estimated from the IP, marked approximate."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import ip_location
from api.helpers import _agent_user_context, _basic_profile_complete
from api.ip_location import client_ip, locate_ip
from api.main import app, current_user
from security.auth import CurrentUser
from storage import get_user_profile, reset_db, save_user_profile, set_estimated_location

USER = CurrentUser(id="signup-user", email="s@example.com", display_name="Sourabh")
JAIPUR = {"country": "India", "country_code": "IN", "region": "Rajasthan", "city": "Jaipur"}


class _FakeReader:
    def get(self, ip: str):
        if ip != "49.36.12.8":
            return None
        return {
            "country": {"iso_code": "IN", "names": {"en": "India"}},
            "subdivisions": [{"names": {"en": "Rajasthan"}}],
            "city": {"names": {"en": "Jaipur (Malviya Nagar)"}},
        }


class IpLocationTest(unittest.TestCase):
    def test_client_ip_skips_private_addresses(self) -> None:
        self.assertEqual(client_ip("49.36.12.8, 10.0.0.2", "127.0.0.1"), "49.36.12.8")
        self.assertIsNone(client_ip("10.0.0.2", "127.0.0.1"))
        self.assertIsNone(client_ip(None, None))

    def test_lookup_reads_country_state_and_city(self) -> None:
        with patch.object(ip_location, "_reader", return_value=_FakeReader()):
            self.assertEqual(locate_ip("49.36.12.8"), JAIPUR)
            self.assertIsNone(locate_ip("8.8.4.4"))

    def test_missing_database_means_no_estimate(self) -> None:
        with patch.object(ip_location, "_reader", return_value=None):
            self.assertIsNone(locate_ip("49.36.12.8"))


class SignupApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock"})
        self.env.start()
        app.dependency_overrides.clear()

        async def signed_in_user() -> CurrentUser:
            return USER

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def _signup(self, adult: bool, forwarded_for: str = "49.36.12.8"):
        with patch("api.routes.profile.locate_ip", side_effect=lambda ip: JAIPUR if ip == "49.36.12.8" else None):
            return self.client.put(
                "/api/me/basics",
                json={"display_name": "Sourabh", "adult_confirmed": adult},
                headers={"X-Forwarded-For": forwarded_for},
            )

    def test_signup_needs_only_a_name_and_the_adult_confirmation(self) -> None:
        self.assertFalse(self.client.get("/api/me/basics").json()["complete"])
        self.assertEqual(self._signup(adult=False).status_code, 422)
        response = self._signup(adult=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["complete"])
        self.assertTrue(self.client.get("/api/me/dating-basics").json()["complete"])  # old path

    def test_location_is_estimated_from_the_ip_and_marked_approximate(self) -> None:
        self._signup(adult=True)
        profile = get_user_profile(USER.id)
        self.assertEqual(
            (profile["city"], profile["region"], profile["country"], profile["location_source"]),
            ("Jaipur", "Rajasthan", "India", "ip"),
        )
        location = _agent_user_context(USER)["location"]
        self.assertIn("Jaipur, Rajasthan, India", location)
        self.assertIn("approximate", location)

    def test_estimate_is_shown_before_signup_without_saving(self) -> None:
        with patch("api.routes.profile.locate_ip", side_effect=lambda ip: JAIPUR if ip == "49.36.12.8" else None):
            response = self.client.get("/api/me/location-estimate", headers={"X-Forwarded-For": "49.36.12.8"})
        self.assertEqual(response.json()["estimate"]["city"], "Jaipur")
        self.assertIsNone(get_user_profile(USER.id))

    def test_a_city_typed_at_signup_is_the_users_own(self) -> None:
        with patch("api.routes.profile.locate_ip", side_effect=lambda ip: JAIPUR if ip == "49.36.12.8" else None):
            self.client.put(
                "/api/me/basics",
                json={"display_name": "Sourabh", "adult_confirmed": True, "city": "Udaipur"},
                headers={"X-Forwarded-For": "49.36.12.8"},
            )
        profile = get_user_profile(USER.id)
        self.assertEqual(
            (profile["city"], profile["country"], profile["location_source"]), ("Udaipur", "India", "user")
        )
        self.assertNotIn("approximate", _agent_user_context(USER)["location"])

    def test_dev_setting_stands_in_for_a_missing_public_ip(self) -> None:
        with patch.dict(os.environ, {"IP_LOCATION_DEV_IP": "49.36.12.8"}):
            self.assertEqual(client_ip(None, "127.0.0.1"), "49.36.12.8")

    def test_no_estimate_without_a_public_ip(self) -> None:
        self._signup(adult=True, forwarded_for="10.0.0.2")
        self.assertIsNone(get_user_profile(USER.id)["city"])


class LocationSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def test_a_city_the_user_gave_is_never_overwritten(self) -> None:
        save_user_profile(USER.id, "prefer_not_to_say", "everyone", "Sourabh", 25, "Pune")
        set_estimated_location(USER.id, JAIPUR)
        profile = get_user_profile(USER.id)
        self.assertEqual((profile["city"], profile["location_source"]), ("Pune", "user"))
        self.assertNotIn("approximate", _agent_user_context(USER)["location"])

    def test_older_profiles_with_an_age_count_as_complete(self) -> None:
        self.assertTrue(_basic_profile_complete({"display_name": "A", "age": 30}))
        self.assertTrue(_basic_profile_complete({"display_name": "A", "adult_confirmed_at": "2026-09-30"}))
        self.assertFalse(_basic_profile_complete({"display_name": "A"}))


if __name__ == "__main__":
    unittest.main()
