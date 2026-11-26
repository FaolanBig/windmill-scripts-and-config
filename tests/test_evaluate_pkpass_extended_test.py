import copy
import importlib.util
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "specific/docker/image_testing/pkpass_builder/evaluate_pkpass_extended_test.py"
)
spec = importlib.util.spec_from_file_location("evaluate_pkpass_extended_test", SCRIPT)
assert spec is not None and spec.loader is not None
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)

CHECK_NAMES = (
    "health", "missing_api_key", "wrong_api_key", "full_contact_and_archive",
    "hidden_position", "optional_fields_and_na", "snake_case_aliases",
    "unicode_and_vcard_escaping", "profile_picture", "reject_invalid_givenName",
    "reject_invalid_surname", "reject_invalid_email", "reject_invalid_showJobPosition",
    "reject_invalid_phoneNumber", "reject_invalid_profilePicture", "reject_missing_name",
    "reject_malformed_json", "unique_serial_numbers",
)
SUCCESS = {
    "finished_successful": "true",
    "error_message": "",
    "container_id": "container-id",
    "container_name": "container-name",
    "checks": [{"name": name, "status": "passed"} for name in CHECK_NAMES],
    "skipped": [
        {"name": "signature_verification", "reason": "Certificates unavailable"},
        {"name": "apple_wallet_installation", "reason": "Device required"},
        {"name": "qr_image_decoding", "reason": "Decoder unavailable"},
    ],
}


class EvaluateExtendedTest(unittest.TestCase):
    def test_success_preserves_skipped_information(self):
        self.assertEqual(evaluator.main(SUCCESS), {
            "finished_successful": "true", "error_message": "", "skipped": SUCCESS["skipped"]
        })

    def test_early_failure_preserves_upstream_error(self):
        result = evaluator.main({"finished_successful": "false", "error_message": "container missing"})
        self.assertEqual(result["finished_successful"], "false")
        self.assertEqual(result["error_message"], "container missing")

    def test_failed_checks_are_included_with_details(self):
        report = copy.deepcopy(SUCCESS)
        report["finished_successful"] = "false"
        report["error_message"] = "1 check(s) failed"
        report["checks"][0].update(status="failed", error="timeout")
        result = evaluator.main(report)
        self.assertEqual(result["finished_successful"], "false")
        self.assertIn("1 check(s) failed", result["error_message"])
        self.assertIn("health: failed (timeout)", result["error_message"])
        self.assertEqual(result["skipped"], SUCCESS["skipped"])

    def test_missing_each_required_check_is_failure(self):
        for name in CHECK_NAMES:
            with self.subTest(name=name):
                report = copy.deepcopy(SUCCESS)
                report["checks"] = [c for c in report["checks"] if c["name"] != name]
                result = evaluator.main(report)
                self.assertEqual(result["finished_successful"], "false")
                self.assertIn(f"Missing required check: {name}", result["error_message"])

    def test_incomplete_or_contradictory_reports_are_rejected(self):
        variants = []
        report = copy.deepcopy(SUCCESS)
        report["checks"][0]["status"] = "skipped"
        variants.append(report)
        report = copy.deepcopy(SUCCESS)
        report["checks"].append({"name": "health", "status": "passed"})
        variants.append(report)
        report = copy.deepcopy(SUCCESS)
        report["checks"].append({"name": "additional_check", "status": "failed", "error": "failed"})
        variants.append(report)
        report = copy.deepcopy(SUCCESS)
        report["checks"].append({"name": [], "status": "passed"})
        variants.append(report)
        report = copy.deepcopy(SUCCESS)
        report["skipped"] = [{"name": "signature_verification"}]
        variants.append(report)
        report = copy.deepcopy(SUCCESS)
        report["container_id"] = ""
        variants.append(report)
        for report in variants:
            with self.subTest(report=report):
                result = evaluator.main(report)
                self.assertEqual(result["finished_successful"], "false")
                self.assertTrue(result["error_message"])

    def test_missing_or_unexpected_results_are_failures(self):
        for report in (None, {}, [], "invalid", {"finished_successful": True}):
            with self.subTest(report=report):
                result = evaluator.main(report)
                self.assertEqual(result["finished_successful"], "false")
                self.assertTrue(result["error_message"])


if __name__ == "__main__":
    unittest.main()
