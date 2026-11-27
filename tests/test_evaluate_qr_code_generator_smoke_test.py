import copy
import importlib.util
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "specific/docker/image_testing/qr-code-generator/evaluate_qr_code_generator_smoke_test.py"
)
spec = importlib.util.spec_from_file_location("evaluate_qr_code_generator_smoke_test", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SUCCESS = {
    "finished_successful": "true",
    "container_id": "container-id",
    "container_name": "container-name",
    "health": {"status": "ok", "http_status": 200},
    "unauthenticated_status": 401,
    "qr_code": {
        "http_status": 200,
        "content_type": "application/json",
        "size_bytes": 1024,
        "is_png": True,
        "has_png_base64": True,
        "has_data_uri": True,
        "type": "text",
        "format": "png",
        "size": 256,
        "recovery": "medium",
        "logo_included": False,
    },
}


class EvaluateQRCodeSmokeTest(unittest.TestCase):
    def test_success(self):
        self.assertEqual(module.main(SUCCESS), {"finished_successful": "true", "error_message": ""})

    def test_upstream_failure(self):
        self.assertEqual(
            module.main({"finished_successful": "false", "error_message": "container stopped"}),
            {"finished_successful": "false", "error_message": "container stopped"},
        )

    def test_missing_or_invalid_results_fail(self):
        for result in (None, {}, [], "invalid", {"finished_successful": False}):
            with self.subTest(result=result):
                actual = module.main(result)
                self.assertEqual(actual["finished_successful"], "false")
                self.assertTrue(actual["error_message"])

    def test_each_qr_field_is_required(self):
        cases = [
            (("health", "status"), "error"),
            (("health", "http_status"), 500),
            (("unauthenticated_status",), 200),
            (("qr_code", "http_status"), 500),
            (("qr_code", "content_type"), "text/plain"),
            (("qr_code", "size_bytes"), 0),
            (("qr_code", "is_png"), False),
            (("qr_code", "type"), "url"),
            (("qr_code", "format"), "jpeg"),
            (("qr_code", "size"), 512),
            (("qr_code", "recovery"), "high"),
            (("qr_code", "logo_included"), True),
        ]
        for path, value in cases:
            with self.subTest(path=path):
                result = copy.deepcopy(SUCCESS)
                target = result
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                actual = module.main(result)
                self.assertEqual(actual["finished_successful"], "false")
                self.assertTrue(actual["error_message"])


if __name__ == "__main__":
    unittest.main()
