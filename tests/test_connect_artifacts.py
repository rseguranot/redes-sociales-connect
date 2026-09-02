import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ConnectArtifactsTests(unittest.TestCase):
    def _assert_valid_graph(self, artifact):
        actions = {item["Identifier"]: item for item in artifact["Actions"]}
        self.assertIn(artifact["StartAction"], actions)
        for action in actions.values():
            transitions = action.get("Transitions") or {}
            if transitions.get("NextAction"):
                self.assertIn(transitions["NextAction"], actions)
            for error in transitions.get("Errors") or []:
                self.assertIn(error["NextAction"], actions)
        return actions

    def test_context_module_has_valid_graph_and_contract_stamp(self):
        module = json.loads((ROOT / "connect" / "context-module.json").read_text(encoding="utf-8"))
        actions = self._assert_valid_graph(module)

        self.assertEqual(module["Version"], "2019-10-30")
        self.assertEqual(actions["ReturnToFlow"]["Type"], "EndFlowModuleExecution")
        self.assertIn("entryPointPosition", module["Metadata"])
        self.assertNotIn("EntryPointPosition", module["Metadata"])

        settings = module["Settings"]
        self.assertEqual(settings["InputParameters"], [])
        self.assertEqual(settings["OutputParameters"], [])
        self.assertEqual(
            {transition["ReferenceName"] for transition in settings["Transitions"]},
            {"Success", "Error"},
        )

        attributes = actions["SetSocialContext"]["Parameters"]["Attributes"]
        self.assertEqual(attributes["social_context_version"], "1.0")
        self.assertEqual(attributes["social_context_status"], "READY")

        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        module_section = template.split("  ConnectContextModule:", 1)[1].split(
            "  DefaultConnectContactFlow:", 1
        )[0]
        template_content = module_section.split("      Content: |", 1)[1].split(
            "      Tags:", 1
        )[0]
        embedded_module = json.loads(
            "\n".join(
                line[8:] if line.startswith("        ") else line
                for line in template_content.strip("\n").splitlines()
            )
        )
        self.assertEqual(embedded_module, module)
        self.assertIn('"Settings": {', module_section)
        self.assertIn('"entryPointPosition":', module_section)
        self.assertNotIn('"EntryPointPosition":', module_section)

    def test_default_contact_flow_invokes_module_and_routes_to_queue(self):
        flow = json.loads(
            (ROOT / "connect" / "default-contact-flow.example.json").read_text(encoding="utf-8")
        )
        actions = self._assert_valid_graph(flow)

        self.assertIn("entryPointPosition", flow["Metadata"])
        self.assertNotIn("EntryPointPosition", flow["Metadata"])
        self.assertEqual(actions["InitializeSocialContext"]["Type"], "InvokeFlowModule")
        self.assertEqual(actions["SetWorkingQueue"]["Type"], "UpdateContactTargetQueue")
        self.assertEqual(actions["TransferToAgentQueue"]["Type"], "TransferContactToQueue")
        self.assertEqual(actions["EndContact"]["Type"], "DisconnectParticipant")


if __name__ == "__main__":
    unittest.main()
