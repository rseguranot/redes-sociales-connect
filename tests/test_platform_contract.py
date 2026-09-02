import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class PlatformContractTests(unittest.TestCase):
    def test_template_keeps_environments_isolated(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        for suffix in ("ingreso", "procesador", "campanas", "multimedia"):
            self.assertIn(
                f"${{ProjectName}}-${{Environment}}-lambda-redes-sociales-{suffix}",
                template,
            )
        self.assertIn("CreateConnectAttachmentsStorage", template)
        self.assertIn("Condition: CreateAttachmentsStorage", template)

    def test_stack_exposes_application_grouping_and_observability(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        self.assertGreaterEqual(template.count("Type: AWS::ResourceGroups::Group"), 2)
        self.assertIn("Type: AWS::CloudWatch::Dashboard", template)
        for logical_name in (
            "IngressLogGroup",
            "ProcessorLogGroup",
            "CampaignLogGroup",
            "MediaLogGroup",
        ):
            self.assertIn(f"  {logical_name}:\n", template.replace("\r\n", "\n"))

    def test_initial_create_rollbacks_do_not_orphan_retained_resources(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        self.assertGreaterEqual(template.count("DeletionPolicy: RetainExceptOnCreate"), 11)
        self.assertIsNone(re.search(r"^\s+DeletionPolicy: Retain$", template, re.MULTILINE))

    def test_connect_attributes_include_channel_neutral_identity(self):
        processor = (ROOT / "src" / "processor" / "app.py").read_text(encoding="utf-8")
        for attribute in (
            "social_channel",
            "social_provider",
            "social_business_id",
            "social_asset_id",
            "social_user_id",
            "social_display_name",
            "social_phone",
            "social_message_id",
        ):
            self.assertIn(f'"{attribute}"', processor)


if __name__ == "__main__":
    unittest.main()
