import copy
import importlib.util
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "specific/docker/image_testing/qr-code-generator/evaluate_qr_code_generator_extended_test.py"
)
spec = importlib.util.spec_from_file_location("evaluate_qr_code_generator_extended_test", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SUCCESS = {
    "finished_successful": "true",
    "error_message": "",
    "container_id": "container-id",
    "container_name": "container-name",
    "checks": [{"name": name, "status": "passed"} for name in module.REQUIRED_CHECKS],
    "skipped": [{
        "name": "qr_payload_decoding",
        "reason": "No QR decoder is assumed available in the container",
    }],
}


class EvaluateQRCodeExtendedTest(unittest.TestCase):
    def test_success(self):
        actual = module.main(SUCCESS)
        self.assertEqual(actual["finished_successful"], "true")
        self.assertEqual(actual["skipped"], SUCCESS["skipped"])

    def test_upstream_failure(self):
        actual = module.main({"finished_successful": "false", "error_message": "container missing"})
        self.assertEqual(actual["finished_successful"], "false")
        self.assertIn("container missing", actual["error_message"])

    def test_failed_check_is_reported(self):
        report = copy.deepcopy(SUCCESS)
        report["checks"][0].update(status="failed", error="timeout")
        actual = module.main(report)
        self.assertEqual(actual["finished_successful"], "false")
        self.assertIn("health: failed", actual["error_message"])

    def test_missing_required_check_fails(self):
        for name in module.REQUIRED_CHECKS:
            with self.subTest(name=name):
                report = copy.deepcopy(SUCCESS)
                report["checks"] = [check for check in report["checks"] if check["name"] != name]
                actual = module.main(report)
                self.assertEqual(actual["finished_successful"], "false")
                self.assertIn(f"Missing required check: {name}", actual["error_message"])

    def test_invalid_reports_fail(self):
        variants = []
        report = copy.deepcopy(SUCCESS)
        report["checks"][0]["status"] = "skipped"
        variants.append(report)
        report = copy.deepcopy(SUCCESS)
        report["checks"].append({"name": "health", "status": "passed"})
        variants.append(report)
        report = copy.deepcopy(SUCCESS)
        report["skipped"] = [{"name": "qr_payload_decoding"}]
        variants.append(report)
        report = copy.deepcopy(SUCCESS)
        report["container_id"] = ""
        variants.append(report)
        for report in variants:
            with self.subTest(report=report):
                actual = module.main(report)
                self.assertEqual(actual["finished_successful"], "false")

    def test_missing_or_unexpected_results_fail(self):
        for report in (None, {}, [], "invalid", {"finished_successful": True}):
            with self.subTest(report=report):
                actual = module.main(report)
                self.assertEqual(actual["finished_successful"], "false")
                self.assertTrue(actual["error_message"])


if __name__ == "__main__":
    unittest.main()
