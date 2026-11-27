#requirements:
#docker==7.1.0
#wmill

import json
import logging
import os
import time
from typing import Any

import docker
import wmill
try:
    from docker.errors import DockerException, NotFound
except ImportError:
    DockerException = getattr(getattr(docker, "errors", None), "DockerException", Exception)

    class NotFound(DockerException):
        pass


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def main(container_id: str, timeout_seconds: int = 60) -> dict[str, Any]:
    """Smoke-test the QR Code API container through Docker exec."""

    logger.info("Starting QR Code API smoke test for container %s", container_id)
    try:
        api_key = wmill.get_variable("f/Image_Testing/qr_code_api_key")
    except Exception:
        logger.error("Failed to retrieve the QR Code API key from Windmill")
        raise ValueError("ERROR: secrets: qr code api key secret is required and missing")

    host = os.environ.get("DOCKER_HOST") or "tcp://docker-test-daemon:2375"
    client = docker.DockerClient(base_url=host, tls=False, timeout=30)

    try:
        client.ping()
        container = client.containers.get(container_id)
    except (DockerException, NotFound) as error:
        logger.error("Unable to access container %s (%s)", container_id, type(error).__name__)
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

    if not isinstance(api_key, str) or not api_key:
        return {
            "finished_successful": "false",
            "container_id": container_id,
            "container_name": container_name,
            "error_message": "API_KEY is missing from the container or script input",
        }

    port = listen_port(container.attrs)
    deadline = time.monotonic() + max(timeout_seconds, 1)
    last_health_error = "No health response"
    health_url = f"http://127.0.0.1:{port}/healthz"

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
            result = container.exec_run(["curl", "-fsS", health_url], stdout=True, stderr=True)
            output = decode_exec_output(result.output)
            if result.exit_code == 0:
                health_payload = parse_json_output(output)
                if health_payload.get("status") == "ok":
                    health = {"status": "ok", "http_status": 200}
                    break
                last_health_error = output.strip() or "Unexpected health response"
            else:
                last_health_error = output.strip() or "Health check failed"
        except DockerException as error:
            last_health_error = str(error)

        time.sleep(1)
    else:
        return {
            "finished_successful": "false",
            "container_id": container_id,
            "container_name": container_name,
            "error_message": f"Timed out waiting for /healthz: {last_health_error}",
        }

    smoke_script = r'''set -eu
base="http://127.0.0.1:${SMOKE_PORT}"
body_file=$(mktemp)
png_file=$(mktemp)
trap 'rm -f "$body_file" "$png_file"' EXIT

unauth_status=$(curl -sS -o "$body_file" -w '%{http_code}' \
  "$base/api/v1/")

status=$(curl -sS -o "$body_file" -w '%{http_code}' \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: ${SMOKE_API_KEY}" \
  --data '{"text":"Windmill smoke test","size":256,"recovery":"medium"}' \
  "$base/api/v1/qr/text")

if [ "$unauth_status" != "401" ]; then
  printf '{"smoke_error":"Unauthenticated API request returned HTTP %s"}' "$unauth_status"
  exit 1
fi

if [ "$status" != "200" ]; then
  printf '{"smoke_error":"Authenticated /qr/text request returned HTTP %s"}' "$status"
  exit 1
fi

if ! grep -q '"type":"text"' "$body_file" || \
   ! grep -q '"format":"png"' "$body_file" || \
   ! grep -q '"size":256' "$body_file" || \
   ! grep -q '"recovery":"medium"' "$body_file" || \
   ! grep -q '"logo_included":false' "$body_file" || \
   ! grep -q '"data_uri":"data:image/png;base64,' "$body_file"; then
  printf '{"smoke_error":"QR response does not contain the expected metadata"}'
  exit 1
fi

png_base64=$(sed -n 's/.*"png_base64":"\([^\"]*\)".*/\1/p' "$body_file")
if [ -z "$png_base64" ]; then
  printf '{"smoke_error":"QR response has no png_base64 field"}'
  exit 1
fi

printf '%s' "$png_base64" | base64 -d > "$png_file" 2>/dev/null || {
  printf '{"smoke_error":"png_base64 is not valid base64"}'
  exit 1
}

signature=$(od -An -tx1 -N8 "$png_file" | tr -d ' \n')
if [ "$signature" != "89504e470d0a1a0a" ]; then
  printf '{"smoke_error":"Decoded QR image is not a PNG"}'
  exit 1
fi

png_size=$(wc -c < "$png_file")
printf '{"unauthenticated_status":401,"qr_code":{"http_status":200,"content_type":"application/json","size_bytes":%s,"is_png":true,"has_png_base64":true,"has_data_uri":true,"type":"text","format":"png","size":256,"recovery":"medium","logo_included":false}}' "$png_size"
'''

    try:
        result = container.exec_run(
            ["sh", "-c", smoke_script],
            environment={"SMOKE_API_KEY": api_key, "SMOKE_PORT": str(port)},
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
            "health": health,
            "error_message": f"Docker exec smoke test failed: {error}",
        }

    if result.exit_code != 0:
        return {
            "finished_successful": "false",
            "container_id": container_id,
            "container_name": container_name,
            "health": health,
            "error_message": details.get("smoke_error", "QR Code API smoke test failed"),
        }

    return {
        "finished_successful": "true",
        "container_id": container_id,
        "container_name": container_name,
        "health": health,
        "unauthenticated_status": details["unauthenticated_status"],
        "qr_code": details["qr_code"],
    }


def listen_port(attrs: Any) -> int:
    if not isinstance(attrs, dict):
        return 8080
    env_entries = attrs.get("Config", {}).get("Env", []) or []
    for entry in env_entries:
        name, separator, value = entry.partition("=")
        if separator and name == "LISTEN_ADDRESS":
            port = value.rsplit(":", 1)[-1]
            try:
                parsed = int(port)
                if 1 <= parsed <= 65535:
                    return parsed
            except ValueError:
                pass
    return 8080


def decode_exec_output(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    if isinstance(output, tuple):
        parts = []
        for part in output:
            if part is None:
                continue
            if isinstance(part, bytes):
                parts.append(part.decode("utf-8", errors="replace"))
            else:
                parts.append(str(part))
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
