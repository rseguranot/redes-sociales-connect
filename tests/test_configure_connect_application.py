import importlib.util
import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "configure_connect_application.py"
SPEC = importlib.util.spec_from_file_location("configure_connect_application", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


class ConfigureConnectApplicationTests(unittest.TestCase):
    def test_merge_preserves_other_apps_and_replaces_same_namespace(self):
        current = [
            {"Namespace": "other-app", "ApplicationPermissions": ["ACCESS"], "Type": "THIRD_PARTY_APPLICATION"},
            {"Namespace": "social-app", "ApplicationPermissions": [], "Type": "THIRD_PARTY_APPLICATION"},
        ]
        merged = module.merge_applications(current, "social-app")
        self.assertEqual([item["Namespace"] for item in merged], ["other-app", "social-app"])
        self.assertEqual(merged[-1]["ApplicationPermissions"], ["ACCESS"])

    def test_invalid_namespace_is_rejected(self):
        with self.assertRaises(ValueError):
            module.merge_applications([], "Invalid Namespace")


if __name__ == "__main__":
    unittest.main()
