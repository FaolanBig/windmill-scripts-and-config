import logging
import os
from typing import Any


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def main(smoke_test_result: dict[str, Any] | None = None) -> dict[str, str]:
    if not isinstance(smoke_test_result, dict):
        logger.error("QR Code API smoke-test result is missing or invalid")
        return {
            "finished_successful": "false",
            "error_message": "QR Code API smoke-test result is missing or invalid",
        }

    if smoke_test_result.get("finished_successful") != "true":
        error = smoke_test_result.get("error_message")
        return {
            "finished_successful": "false",
            "error_message": error if isinstance(error, str) and error else
            "QR Code API smoke test did not report success",
        }

    errors: list[str] = []
    for field in ("container_id", "container_name"):
        value = smoke_test_result.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} is missing or invalid")

    health = smoke_test_result.get("health")
    if not isinstance(health, dict):
        errors.append("health result is missing or invalid")
    else:
        if health.get("status") != "ok":
            errors.append("health status is not ok")
        if type(health.get("http_status")) is not int or health["http_status"] != 200:
            errors.append("health HTTP status is not 200")

    unauthenticated_status = smoke_test_result.get("unauthenticated_status")
    if type(unauthenticated_status) is not int or unauthenticated_status != 401:
        errors.append("unauthenticated HTTP status is not 401")

    qr_code = smoke_test_result.get("qr_code")
    if not isinstance(qr_code, dict):
        errors.append("qr_code result is missing or invalid")
    else:
        if type(qr_code.get("http_status")) is not int or qr_code["http_status"] != 200:
            errors.append("QR-code HTTP status is not 200")
        content_type = qr_code.get("content_type")
        if not isinstance(content_type, str) or "application/json" not in content_type:
            errors.append("QR-code content type is invalid")
        size = qr_code.get("size_bytes")
        if type(size) is not int or size <= 0:
            errors.append("QR-code PNG size is not a positive integer")
        if qr_code.get("type") != "text":
            errors.append("QR-code type is not text")
        if qr_code.get("format") != "png":
            errors.append("QR-code format is not png")
        if qr_code.get("size") != 256:
            errors.append("QR-code size is not 256")
        if qr_code.get("recovery") != "medium":
            errors.append("QR-code recovery is not medium")
        for field in ("is_png", "has_png_base64", "has_data_uri"):
            if qr_code.get(field) is not True:
                errors.append(f"QR-code {field} is not true")
        if qr_code.get("logo_included") is not False:
            errors.append("QR-code logo_included is not false")

    if errors:
        logger.error("QR Code API smoke-test result failed validation")
        return {
            "finished_successful": "false",
            "error_message": "; ".join(errors),
        }

    logger.info("QR Code API smoke test succeeded")
    return {"finished_successful": "true", "error_message": ""}
