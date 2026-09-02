import importlib.util
import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "handoff_connect_contacts.py"
SPEC = importlib.util.spec_from_file_location("handoff_connect_contacts", SCRIPT)
handoff = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(handoff)


class HandoffIdentityTests(unittest.TestCase):
    def test_requires_explicit_phone(self):
        self.assertIsNone(handoff._identity({
            "social_user_id": "BSUID-123",
            "social_username": "cliente",
        }))

    def test_preserves_bsuid_as_identity_and_phone_separately(self):
        identity = handoff._identity({
            "social_user_id": "BSUID-123",
            "social_phone": "+18095550100",
            "social_username": "cliente",
            "social_display_name": "Cliente",
        })
        self.assertEqual("BSUID-123", identity["id"])
        self.assertEqual("18095550100", identity["phone"])

    def test_rejects_username_as_phone(self):
        self.assertIsNone(handoff._identity({"social_phone": "cliente_demo"}))


if __name__ == "__main__":
    unittest.main()
