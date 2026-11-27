import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class DockerException(Exception):
    pass


class NotFound(DockerException):
    pass


docker = types.ModuleType("docker")
docker.DockerClient = MagicMock()
docker_errors = types.ModuleType("docker.errors")
docker_errors.DockerException = DockerException
docker_errors.NotFound = NotFound
wmill = types.ModuleType("wmill")
wmill.get_variable = MagicMock(return_value="test-api-key-at-least-16")

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"docker": docker, "docker.errors": docker_errors, "wmill": wmill}):
        spec.loader.exec_module(module)
    return module


smoke = load(
    "qr_code_generator_smoke_test",
    ROOT / "specific/docker/image_testing/qr-code-generator/qr_code_generator_smoke_test.py",
)
extended = load(
    "qr_code_generator_extended_test",
    ROOT / "specific/docker/image_testing/qr-code-generator/qr_code_generator_extended_test.py",
)


class QRCodeTestScripts(unittest.TestCase):
    def setUp(self):
        docker.DockerClient.reset_mock()
        wmill.get_variable.reset_mock()
        wmill.get_variable.return_value = "test-api-key-at-least-16"
        wmill.get_variable.side_effect = None

    def test_smoke_success_and_key_handling(self):
        client = MagicMock()
        docker.DockerClient.return_value = client
        container = client.containers.get.return_value
        container.status = "running"
        container.name = "qr-container"
        container.attrs = {"Config": {"Env": ["LISTEN_ADDRESS=:8080", "API_KEY=test-api-key-at-least-16"]}}
        container.exec_run.side_effect = [
            types.SimpleNamespace(exit_code=0, output=b'{"status":"ok"}'),
            types.SimpleNamespace(exit_code=0, output=json.dumps({
                "unauthenticated_status": 401,
                "qr_code": {"http_status": 200, "content_type": "application/json", "size_bytes": 100},
            }).encode()),
        ]
        result = smoke.main("container")
        self.assertEqual(result["finished_successful"], "true")
        self.assertEqual(result["container_name"], "qr-container")
        args, kwargs = container.exec_run.call_args_list[-1]
        self.assertEqual(args[0][0], "sh")
        self.assertEqual(kwargs["environment"]["SMOKE_API_KEY"], "test-api-key-at-least-16")

    def test_extended_exec_report(self):
        client = MagicMock()
        docker.DockerClient.return_value = client
        container = client.containers.get.return_value
        container.status = "running"
        container.name = "qr-container"
        container.attrs = {"Config": {"Env": ["LISTEN_ADDRESS=:8080"]}}
        container.exec_run.return_value = types.SimpleNamespace(
            exit_code=0,
            output=json.dumps({
                "finished_successful": "true",
                "error_message": "",
                "checks": [],
                "skipped": [{"name": "qr_payload_decoding", "reason": "Decoder unavailable"}],
            }).encode(),
        )
        result = extended.main("container")
        self.assertEqual(result["finished_successful"], "true")
        self.assertEqual(result["container_name"], "qr-container")
        args, kwargs = container.exec_run.call_args
        self.assertEqual(args[0][0], "sh")
        self.assertEqual(kwargs["environment"]["QR_CODE_TEST_API_KEY"], "test-api-key-at-least-16")

    def test_missing_inputs_and_exec_failure(self):
        self.assertEqual(extended.main("")["finished_successful"], "false")
        self.assertEqual(extended.main("container", 0)["finished_successful"], "false")

        client = MagicMock()
        docker.DockerClient.return_value = client
        container = client.containers.get.return_value
        container.status = "running"
        container.name = "qr-container"
        container.attrs = {"Config": {"Env": []}}
        container.exec_run.return_value = types.SimpleNamespace(exit_code=1, output=b"secret")
        result = extended.main("container")
        self.assertEqual(result["finished_successful"], "false")
        self.assertNotIn("secret", result["error_message"])


if __name__ == "__main__":
    unittest.main()
