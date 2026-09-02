import pathlib
import unittest


class DeployScriptTests(unittest.TestCase):
    def test_parameter_overrides_use_a_file_and_omit_empty_values(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        script = (repo_root / "scripts" / "deploy.ps1").read_text(encoding="utf-8-sig")

        self.assertIn(
            "if ([string]::IsNullOrEmpty([string]$entry.Value)) { continue }",
            script,
        )
        self.assertIn(
            "$parameterOverrides[[string]$entry.Key] = [string]$entry.Value",
            script,
        )
        self.assertIn(
            "$deployArguments += @('--parameter-overrides', \"file://$parameterOverridesPath\")",
            script,
        )
        self.assertNotIn(
            '$deployArguments += "$($entry.Key)=$([string]$entry.Value)"',
            script,
        )


if __name__ == "__main__":
    unittest.main()
