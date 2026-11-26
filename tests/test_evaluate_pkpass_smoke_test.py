import copy
import importlib.util
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "specific/docker/image_testing/pkpass_builder/evaluate_pkpass_smoke_test.py"
)
spec = importlib.util.spec_from_file_location("evaluate_pkpass_smoke_test", SCRIPT)
assert spec is not None and spec.loader is not None
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)

SUCCESS = {
    "health": {"status": "ok", "http_status": 200},
    "apple_pass": {
        "is_zip": True,
        "crc_valid": True,
        "size_bytes": 4677,
        "http_status": 200,
        "content_type": "application/vnd.apple.pkpass",
        "has_pass_json": True,
    },
    "container_id": "73b5d9bbfffb3eab386688996dc2d126a8da8b09e86d719bb5ddd4d892c6eb04",
    "container_name": "d7a1b750df9f44d38997739a9c42dc69",
    "finished_successful": "true",
    "unauthenticated_status": 401,
}


class EvaluateSmokeTest(unittest.TestCase):
    def test_success_and_content_type_parameters(self):
        result = copy.deepcopy(SUCCESS)
        expected = {"finished_successful": "true", "error_message": ""}
        self.assertEqual(evaluator.main(result), expected)
        result["apple_pass"]["content_type"] += "; charset=binary"
        self.assertEqual(evaluator.main(result), expected)

    def test_upstream_failure_preserves_message(self):
        self.assertEqual(
            evaluator.main({"finished_successful": "false", "error_message": "container stopped"}),
            {"finished_successful": "false", "error_message": "container stopped"},
        )

    def test_missing_or_unexpected_results_are_failures(self):
        for result in (None, {}, [], "invalid", {"finished_successful": False}):
            with self.subTest(result=result):
                actual = evaluator.main(result)
                self.assertEqual(actual["finished_successful"], "false")
                self.assertTrue(actual["error_message"])

    def test_each_success_field_is_required_and_valid(self):
        cases = [
            (("container_id",), ""),
            (("container_name",), None),
            (("health",), None),
            (("health", "status"), "error"),
            (("health", "http_status"), 500),
            (("unauthenticated_status",), 200),
            (("apple_pass",), None),
            (("apple_pass", "http_status"), 500),
            (("apple_pass", "content_type"), "application/json"),
            (("apple_pass", "size_bytes"), 0),
            (("apple_pass", "size_bytes"), True),
            (("apple_pass", "is_zip"), False),
            (("apple_pass", "has_pass_json"), None),
            (("apple_pass", "crc_valid"), 1),
        ]
        for path, value in cases:
            with self.subTest(path=path, value=value):
                result = copy.deepcopy(SUCCESS)
                target = result
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                actual = evaluator.main(result)
                self.assertEqual(actual["finished_successful"], "false")
                self.assertTrue(actual["error_message"])


if __name__ == "__main__":
    unittest.main()
