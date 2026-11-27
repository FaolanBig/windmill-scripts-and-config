#requirements:
#docker==7.1.0
#wmill

import json
import logging
import os
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


def run_inside_container(timeout_seconds: int) -> str:
    """Shell test source executed in the Docker container; curl and sh are installed."""

    return r'''set -u
base="http://127.0.0.1:${QR_CODE_TEST_PORT}"
resp=$(mktemp)
png=$(mktemp)
trap 'rm -f "$resp" "$png"' EXIT

checks=""
failed=0
sep=""
add_pass() {
  checks="${checks}${sep}{\"name\":\"$1\",\"status\":\"passed\"}"
  sep="," 
}
add_fail() {
  failed=$((failed + 1))
  checks="${checks}${sep}{\"name\":\"$1\",\"status\":\"failed\",\"error\":\"$2\"}"
  sep="," 
}

post_json() {
  path=$1
  body=$2
  auth_mode=$3
  case "$auth_mode" in
    x) status=$(curl -sS -o "$resp" -w '%{http_code}' -H 'Content-Type: application/json' -H "X-API-Key: ${QR_CODE_TEST_API_KEY}" --data "$body" "$base$path") ;;
    bearer) status=$(curl -sS -o "$resp" -w '%{http_code}' -H 'Content-Type: application/json' -H "Authorization: Bearer ${QR_CODE_TEST_API_KEY}" --data "$body" "$base$path") ;;
    none) status=$(curl -sS -o "$resp" -w '%{http_code}' -H 'Content-Type: application/json' --data "$body" "$base$path") ;;
    wrong) status=$(curl -sS -o "$resp" -w '%{http_code}' -H 'Content-Type: application/json' -H 'X-API-Key: definitely-wrong-key' --data "$body" "$base$path") ;;
  esac
}

health_status="000"
i=0
while [ "$i" -lt "${QR_CODE_TEST_TIMEOUT}" ]; do
  health_status=$(curl -sS -o "$resp" -w '%{http_code}' "$base/healthz" 2>/dev/null || true)
  if [ "$health_status" = "200" ] && grep -q '"status":"ok"' "$resp"; then
    break
  fi
  i=$((i + 1))
  sleep 1
done
if [ "$health_status" = "200" ] && grep -q '"status":"ok"' "$resp"; then
  add_pass health
else
  add_fail health "healthz did not become ready"
fi

ready_status=$(curl -sS -o "$resp" -w '%{http_code}' "$base/readyz")
if [ "$ready_status" = "200" ] && grep -q '"status":"ready"' "$resp"; then
  add_pass readiness
else
  add_fail readiness "readyz did not return ready"
fi

openapi_status=$(curl -sS -o "$resp" -w '%{http_code}' "$base/openapi.yaml")
if [ "$openapi_status" = "200" ] && grep -q 'openapi:' "$resp"; then
  add_pass openapi
else
  add_fail openapi "OpenAPI specification is unavailable"
fi

missing_status=$(curl -sS -o "$resp" -w '%{http_code}' "$base/api/v1/")
if [ "$missing_status" = "401" ]; then
  add_pass missing_api_key
else
  add_fail missing_api_key "missing API key returned HTTP $missing_status"
fi

wrong_status=$(curl -sS -o "$resp" -w '%{http_code}' -H 'X-API-Key: definitely-wrong-key' "$base/api/v1/")
if [ "$wrong_status" = "401" ]; then
  add_pass wrong_api_key
else
  add_fail wrong_api_key "wrong API key returned HTTP $wrong_status"
fi

bearer_status=$(curl -sS -o "$resp" -w '%{http_code}' -H "Authorization: Bearer ${QR_CODE_TEST_API_KEY}" "$base/api/v1/")
if [ "$bearer_status" = "200" ]; then
  add_pass bearer_auth
else
  add_fail bearer_auth "Bearer authentication returned HTTP $bearer_status"
fi

x_status=$(curl -sS -o "$resp" -w '%{http_code}' -H "X-API-Key: ${QR_CODE_TEST_API_KEY}" "$base/api/v1/")
if [ "$x_status" = "200" ] && grep -q '"endpoints"' "$resp"; then
  add_pass api_index
else
  add_fail api_index "X-API-Key API index request failed"
fi

check_qr_endpoint() {
  name=$1
  path=$2
  body=$3
  expected_type=$4
  post_json "$path" "$body" x
  if [ "$status" = "200" ] && grep -q '"type":"'"$expected_type"'"' "$resp" && grep -q '"format":"png"' "$resp" && grep -q '"png_base64":"' "$resp" && grep -q '"data_uri":"data:image/png;base64,' "$resp"; then
    add_pass "$name"
  else
    add_fail "$name" "endpoint returned HTTP $status or an invalid QR response"
  fi
}

check_qr_endpoint url_qr /api/v1/qr/url '{"url":"https://example.org","size":256,"recovery":"medium"}' url
check_qr_endpoint vcard_qr /api/v1/qr/vcard '{"first_name":"Ada","last_name":"Lovelace","organization":"Analytical Engines","email":"ada@example.org","size":256,"recovery":"medium"}' vcard
check_qr_endpoint wifi_qr /api/v1/qr/wifi '{"ssid":"Office-Guest","password":"a-strong-password","security":"WPA","hidden":false,"size":256,"recovery":"medium"}' wifi
check_qr_endpoint calendar_qr /api/v1/qr/calendar '{"title":"Project review","description":"Release review","location":"Conference Room","start":"2026-12-01T09:30:00Z","end":"2026-12-01T10:30:00Z","timezone":"Europe/London","size":256,"recovery":"medium"}' calendar
check_qr_endpoint text_qr /api/v1/qr/text '{"text":"Extended QR test","size":256,"recovery":"medium"}' text
check_qr_endpoint file_qr /api/v1/qr/file '{"filename":"hello.txt","mime_type":"text/plain","base64_content":"SGVsbG8=","size":256,"recovery":"medium"}' file
check_qr_endpoint number_qr /api/v1/qr/number '{"number":"+1 555 0100","size":256,"recovery":"medium"}' number
check_qr_endpoint email_qr /api/v1/qr/email '{"email":"ada@example.org","subject":"QR test","body":"Hello","size":256,"recovery":"medium"}' email
check_qr_endpoint sms_qr /api/v1/qr/sms '{"phone":"+15550100","body":"Hello","size":256,"recovery":"medium"}' sms
check_qr_endpoint geolocation_qr /api/v1/qr/geolocation '{"latitude":51.5074,"longitude":-0.1278,"label":"London","size":256,"recovery":"medium"}' geolocation

post_json /api/v1/qr/text '{"text":"Image options test","size":512,"recovery":"high"}' x
if [ "$status" = "200" ] && grep -q '"size":512' "$resp" && grep -q '"recovery":"high"' "$resp"; then
  add_pass image_options
else
  add_fail image_options "size or recovery options were not honored"
fi

post_json /api/v1/qr/text '{"text":"Invalid size","size":127,"recovery":"medium"}' x
if [ "$status" = "400" ]; then
  post_json /api/v1/qr/text '{"text":"Invalid recovery","size":256,"recovery":"invalid"}' x
fi
if [ "$status" = "400" ]; then
  add_pass invalid_image_options
else
  add_fail invalid_image_options "invalid size or recovery did not return HTTP 400"
fi

logo_base64=$(base64 -w0 /app/assets/fallback-logo.png)
post_json /api/v1/qr/text '{"text":"Custom logo test","size":256,"recovery":"medium","show_logo":true,"logo_png_base64":"'"$logo_base64"'"}' x
if [ "$status" = "200" ] && grep -q '"logo_included":true' "$resp" && grep -q '"logo_source":"custom"' "$resp"; then
  add_pass custom_logo
else
  add_fail custom_logo "custom PNG logo was not accepted"
fi

post_json /api/v1/qr/text '{"text":"Fallback logo test","size":256,"recovery":"medium","show_logo":true}' x
if [ "$status" = "200" ] && grep -q '"logo_included":true' "$resp" && grep -q '"logo_source":"fallback"' "$resp"; then
  add_pass fallback_logo
else
  add_fail fallback_logo "fallback logo was not used"
fi

multipart_status=$(curl -sS -o "$resp" -w '%{http_code}' -H "X-API-Key: ${QR_CODE_TEST_API_KEY}" -F 'url=https://example.org/multipart' -F 'size=256' -F 'recovery=high' -F 'show_logo=true' -F 'logo=@/app/assets/fallback-logo.png;type=image/png' "$base/api/v1/qr/url")
if [ "$multipart_status" = "200" ] && grep -q '"type":"url"' "$resp" && grep -q '"logo_source":"custom"' "$resp"; then
  add_pass multipart_logo
else
  add_fail multipart_logo "multipart logo request failed"
fi

payload_valid=1
post_json /api/v1/qr/url '{"url":"not-a-url","size":256,"recovery":"medium"}' x
[ "$status" = "400" ] || payload_valid=0
post_json /api/v1/qr/vcard '{"first_name":"","last_name":"","size":256,"recovery":"medium"}' x
[ "$status" = "400" ] || payload_valid=0
post_json /api/v1/qr/wifi '{"ssid":"Office","password":"","security":"WPA","size":256,"recovery":"medium"}' x
[ "$status" = "400" ] || payload_valid=0
post_json /api/v1/qr/calendar '{"title":"Bad date","start":"not-a-date","all_day":false,"size":256,"recovery":"medium"}' x
[ "$status" = "400" ] || payload_valid=0
post_json /api/v1/qr/text '{"text":"","size":256,"recovery":"medium"}' x
[ "$status" = "400" ] || payload_valid=0
post_json /api/v1/qr/number '{"number":"abc","size":256,"recovery":"medium"}' x
[ "$status" = "400" ] || payload_valid=0
post_json /api/v1/qr/email '{"email":"not-an-email","size":256,"recovery":"medium"}' x
[ "$status" = "400" ] || payload_valid=0
if [ "$payload_valid" = "1" ]; then
  add_pass payload_validation
else
  add_fail payload_validation "one or more invalid payloads did not return HTTP 400"
fi

malformed_status=$(curl -sS -o "$resp" -w '%{http_code}' -H 'Content-Type: application/json' -H "X-API-Key: ${QR_CODE_TEST_API_KEY}" --data '{' "$base/api/v1/qr/text")
if [ "$malformed_status" = "400" ]; then
  add_pass malformed_json
else
  add_fail malformed_json "malformed JSON returned HTTP $malformed_status"
fi

post_json /api/v1/qr/text '{"text":"Unknown field","unexpected":"value","size":256,"recovery":"medium"}' x
if [ "$status" = "400" ]; then
  add_pass unknown_fields
else
  add_fail unknown_fields "unknown JSON field did not return HTTP 400"
fi

post_json /api/v1/qr/text '{"text":"PNG validation test","size":256,"recovery":"medium"}' x
png_base64=$(sed -n 's/.*"png_base64":"\([^\"]*\)".*/\1/p' "$resp")
printf '%s' "$png_base64" | base64 -d > "$png" 2>/dev/null
signature=$(od -An -tx1 -N8 "$png" | tr -d ' \n')
if [ "$status" = "200" ] && [ -n "$png_base64" ] && [ "$signature" = "89504e470d0a1a0a" ]; then
  add_pass png_integrity
else
  add_fail png_integrity "png_base64 did not contain a valid PNG"
fi

if [ "$failed" -eq 0 ]; then
  finished=true
  error_message=""
else
  finished=false
  error_message="${failed} check(s) failed"
fi

printf '{"finished_successful":"%s","error_message":"%s","checks":[%s],"skipped":[{"name":"qr_payload_decoding","reason":"No QR decoder is assumed available in the container"}]}' "$finished" "$error_message" "$checks"
'''


def main(container_id: str, timeout_seconds: int = 60) -> dict[str, Any]:
    if not container_id or not container_id.strip():
        return {"finished_successful": "false", "error_message": "container_id is required"}
    if timeout_seconds < 1:
        return {"finished_successful": "false", "error_message": "timeout_seconds must be at least 1"}

    try:
        api_key = wmill.get_variable("f/Image_Testing/qr_code_api_key")
    except Exception:
        logger.error("Failed to retrieve the QR Code API key from Windmill")
        return {"finished_successful": "false", "error_message": "Could not retrieve QR Code API key"}
    if not isinstance(api_key, str) or not api_key:
        return {"finished_successful": "false", "error_message": "QR Code API key is missing"}

    client = None
    try:
        client = docker.DockerClient(
            base_url=os.environ.get("DOCKER_HOST") or "tcp://docker-test-daemon:2375",
            tls=False,
            timeout=max(30, timeout_seconds + 300),
        )
        client.ping()
        container = client.containers.get(container_id)
        container.reload()
        if container.status != "running":
            return {"finished_successful": "false", "error_message": f"Container is not running: {container.status}"}

        port = listen_port(container.attrs)
        source = run_inside_container(timeout_seconds)
        result = container.exec_run(
            ["sh", "-c", source],
            environment={
                "QR_CODE_TEST_API_KEY": api_key,
                "QR_CODE_TEST_PORT": str(port),
                "QR_CODE_TEST_TIMEOUT": str(timeout_seconds),
            },
            stdout=True,
            stderr=True,
        )
        output = decode_exec_output(result.output)
        if result.exit_code != 0:
            logger.error("Extended QR Code test process failed with exit code %s", result.exit_code)
            return {
                "finished_successful": "false",
                "error_message": "Test process failed; verify the container has curl and sh",
            }
        try:
            report = json.loads(output)
        except json.JSONDecodeError:
            return {"finished_successful": "false", "error_message": "Test process returned invalid JSON"}
        if not isinstance(report, dict) or report.get("finished_successful") not in ("true", "false"):
            return {"finished_successful": "false", "error_message": "Test process returned an invalid report"}
        report["container_id"] = container_id
        report["container_name"] = container.name or container_id
        return report
    except (DockerException, NotFound) as error:
        logger.error("Docker operation failed during QR Code test (%s)", type(error).__name__)
        return {"finished_successful": "false", "error_message": f"Docker operation failed: {error}"}
    finally:
        if client is not None:
            client.close()


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
