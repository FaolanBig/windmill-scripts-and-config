import wmill
#requirements:
#docker==7.1.0

import json
import os
import time
from typing import Any

import docker
from docker.errors import DockerException, NotFound


def main(
    container_id: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """
    Smoke-test a Windmill-managed PKPass API container.

    - Waits for /health to respond successfully.
    - Verifies unauthenticated requests return 401.
    - Creates an Apple Wallet pass and validates the returned PKPass ZIP.
    """

    try:
        api_key = wmill.get_variable("f/Image_Testing/pkpass_api_key")
    except Exception:
        raise ValueError("ERROR: secrets: pkpass api key secret is required and missing")

    host = os.environ.get("DOCKER_HOST") or "tcp://docker-test-daemon:2375"
    client = docker.DockerClient(base_url=host, tls=False, timeout=30)

    try:
        client.ping()
        container = client.containers.get(container_id)
    except (DockerException, NotFound) as error:
        return {
            "finished_successful": "false",
            "error_message": f"Unable to access container: {error}",
        }

    container.reload()
    container_name = container.name or container_id

    if container.status != "running":
        return {
            "finished_successful": "false",
            "container_id": container_id,
            "container_name": container_name,
            "error_message": f"Container is not running: {container.status}",
        }

    if api_key is None:
        for entry in container.attrs.get("Config", {}).get("Env", []) or []:
            name, separator, value = entry.partition("=")
            if separator and name == "API_KEY":
                api_key = value
                break

    if not api_key:
        return {
            "finished_successful": "false",
            "container_id": container_id,
            "container_name": container_name,
            "error_message": "API_KEY is missing from the container or script input",
        }

    health_script = r"""
import json
import urllib.request

try:
    with urllib.request.urlopen(
        "http://127.0.0.1:8000/health",
        timeout=3,
    ) as response:
        status = response.status
        payload = json.loads(response.read().decode("utf-8"))

    if status != 200 or payload != {"status": "ok"}:
        raise RuntimeError("Unexpected health response")

    print(json.dumps({"status": "ok", "http_status": status}))
except Exception as error:
    print(str(error))
    raise SystemExit(1)
"""

    deadline = time.monotonic() + max(timeout_seconds, 1)
    last_health_error = "No health response"

    while time.monotonic() < deadline:
        container.reload()

        if container.status != "running":
            return {
                "finished_successful": "false",
                "container_id": container_id,
                "container_name": container_name,
                "error_message": f"Container stopped before it became healthy: {container.status}",
            }

        try:
            result = container.exec_run(
                ["python", "-c", health_script],
                stdout=True,
                stderr=True,
            )
            output = decode_exec_output(result.output)

            if result.exit_code == 0:
                health = parse_json_output(output)
                break

            last_health_error = output.strip() or "Health check failed"
        except DockerException as error:
            last_health_error = str(error)

        time.sleep(1)
    else:
        return {
            "finished_successful": "false",
            "container_id": container_id,
            "container_name": container_name,
            "error_message": f"Timed out waiting for /health: {last_health_error}",
        }

    pass_script = r"""
import json
import os
import urllib.error
import urllib.request
import zipfile
from io import BytesIO

payload = {
    "givenName": "Windmill",
    "surname": "Smoke",
    "academicDegree": "Test",
    "company": "Windmill Smoke Test",
    "jobPosition": "API Tester",
    "showJobPosition": True,
    "email": "smoke-test@example.org",
    "phoneNumber": "+1 555 0100",
    "department": "Automation",
    "street": "1 Smoke Test Street",
    "postalCode": "00000",
    "city": "Test City",
    "country": "Test Country",
}

body = json.dumps(payload).encode("utf-8")

def post_pass(api_key):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    request = urllib.request.Request(
        "http://127.0.0.1:8000/passes",
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()

try:
    unauthenticated_status, _, _ = post_pass(None)
    if unauthenticated_status != 401:
        raise RuntimeError(
            "Unauthenticated /passes request returned HTTP "
            + str(unauthenticated_status)
        )

    key = os.environ.get("SMOKE_API_KEY")
    if not key:
        raise RuntimeError("SMOKE_API_KEY was not provided")

    status, headers, archive_bytes = post_pass(key)
    if status != 200:
        raise RuntimeError("/passes returned HTTP " + str(status))

    content_type = headers.get("Content-Type", "")
    if "application/vnd.apple.pkpass" not in content_type:
        raise RuntimeError("Unexpected pass content type")

    if not archive_bytes.startswith(b"PK"):
        raise RuntimeError("Response is not a PKPass ZIP archive")

    archive = zipfile.ZipFile(BytesIO(archive_bytes), "r")
    names = set(archive.namelist())

    if "pass.json" not in names:
        raise RuntimeError("PKPass archive does not contain pass.json")

    if archive.testzip() is not None:
        raise RuntimeError("PKPass archive CRC validation failed")

    print(json.dumps({
        "unauthenticated_status": 401,
        "apple_pass": {
            "http_status": 200,
            "content_type": content_type,
            "size_bytes": len(archive_bytes),
            "is_zip": True,
            "has_pass_json": True,
            "crc_valid": True,
        },
    }))
except Exception as error:
    print(json.dumps({"smoke_error": str(error)}))
    raise SystemExit(1)
"""

    try:
        result = container.exec_run(
            ["python", "-c", pass_script],
            environment={"SMOKE_API_KEY": api_key},
            stdout=True,
            stderr=True,
        )
        output = decode_exec_output(result.output)
        details = parse_json_output(output)
    except DockerException as error:
        return {
            "finished_successful": "false",
            "container_id": container_id,
            "container_name": container_name,
            "error_message": f"Docker exec smoke test failed: {error}",
        }

    if result.exit_code != 0:
        return {
            "finished_successful": "false",
            "container_id": container_id,
            "container_name": container_name,
            "health": health,
            "error_message": details.get(
                "smoke_error",
                "PKPass smoke test failed",
            ),
        }

    return {
        "finished_successful": "true",
        "container_id": container_id,
        "container_name": container_name,
        "health": health,
        "unauthenticated_status": details["unauthenticated_status"],
        "apple_pass": details["apple_pass"],
    }


def decode_exec_output(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    if isinstance(output, tuple):
        parts = [
            part.decode("utf-8", errors="replace")
            if isinstance(part, bytes)
            else str(part)
            for part in output
            if part is not None
        ]
        return "\n".join(parts)
    return str(output)


def parse_json_output(output: str) -> dict[str, Any]:
    for line in reversed(output.strip().splitlines()):
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return {}