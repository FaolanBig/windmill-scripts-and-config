import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class DockerException(Exception):
    pass


docker = types.ModuleType("docker")
docker.DockerClient = MagicMock()
docker_errors = types.ModuleType("docker.errors")
docker_errors.DockerException = DockerException
wmill = types.ModuleType("wmill")
wmill.get_variable = MagicMock(return_value="test-api-key")
script = (
    Path(__file__).resolve().parents[1]
    / "specific/docker/image_testing/pkpass_builder/pkpass_extended_test.py"
)
spec = importlib.util.spec_from_file_location("pkpass_extended_test", script)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"docker": docker, "docker.errors": docker_errors, "wmill": wmill}):
    spec.loader.exec_module(module)


class ExtendedTest(unittest.TestCase):
    def setUp(self):
        docker.DockerClient.reset_mock()
        wmill.get_variable.reset_mock()
        wmill.get_variable.return_value = "test-api-key"
        wmill.get_variable.side_effect = None

    def test_missing_inputs_are_rejected(self):
        self.assertEqual(module.main("")["finished_successful"], "false")
        self.assertEqual(module.main("container", 0)["finished_successful"], "false")
        docker.DockerClient.assert_not_called()
        wmill.get_variable.assert_not_called()

    def test_exec_report_and_key_handling(self):
        client = MagicMock()
        docker.DockerClient.return_value = client
        container = client.containers.get.return_value
        container.status = "running"
        container.name = "test-container"
        container.exec_run.return_value.exit_code = 0
        container.exec_run.return_value.output = json.dumps({
            "finished_successful": "true", "error_message": "", "checks": []
        }).encode()
        result = module.main("container")
        self.assertEqual(result["finished_successful"], "true")
        self.assertEqual(result["container_name"], "test-container")
        args, kwargs = container.exec_run.call_args
        self.assertNotIn("test-api-key", args[0][2])
        self.assertEqual(kwargs["environment"]["PKPASS_TEST_API_KEY"], "test-api-key")
        client.close.assert_called_once()

    def test_exec_and_bad_report_failures(self):
        client = MagicMock()
        docker.DockerClient.return_value = client
        container = client.containers.get.return_value
        container.status = "running"
        container.exec_run.return_value.exit_code = 1
        container.exec_run.return_value.output = b"secret output"
        result = module.main("container")
        self.assertEqual(result["finished_successful"], "false")
        self.assertNotIn("secret output", result["error_message"])
        container.exec_run.return_value.exit_code = 0
        container.exec_run.return_value.output = b"not-json"
        self.assertEqual(module.main("container")["finished_successful"], "false")
        container.exec_run.return_value.output = b"{}"
        self.assertEqual(module.main("container")["finished_successful"], "false")

    def test_invalid_archive_cannot_pass(self):
        class Response(io.BytesIO):
            def __init__(self, status, body, content_type="application/json"):
                super().__init__(body)
                self.status = status
                self.headers = {"Content-Type": content_type}

        def fake_open(request, timeout):
            if request.full_url.endswith("/health"):
                return Response(200, b'{"status":"ok"}')
            key = request.headers.get("X-api-key")
            if key != "test-api-key":
                return Response(401, b"")
            return Response(200, b"not-a-zip", "application/vnd.apple.pkpass")

        pil = types.ModuleType("PIL")
        pil.Image = MagicMock()
        with patch.dict(sys.modules, {"PIL": pil}), \
                patch.dict(os.environ, {"PKPASS_TEST_API_KEY": "test-api-key"}), \
                patch("urllib.request.urlopen", fake_open):
            result = module.run_inside_container(1)
        checks = {item["name"]: item for item in result["checks"]}
        self.assertEqual(result["finished_successful"], "false")
        self.assertEqual(checks["missing_api_key"]["status"], "passed")
        self.assertEqual(checks["full_contact_and_archive"]["status"], "failed")
        self.assertIn("ZIP", checks["full_contact_and_archive"]["error"])


if __name__ == "__main__":
    unittest.main()
