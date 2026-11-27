import logging
import os
from typing import Any


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

REQUIRED_CHECKS = (
    "health",
    "readiness",
    "openapi",
    "missing_api_key",
    "wrong_api_key",
    "bearer_auth",
    "api_index",
    "url_qr",
    "vcard_qr",
    "wifi_qr",
    "calendar_qr",
    "text_qr",
    "file_qr",
    "number_qr",
    "email_qr",
    "sms_qr",
    "geolocation_qr",
    "image_options",
    "invalid_image_options",
    "custom_logo",
    "fallback_logo",
    "multipart_logo",
    "payload_validation",
    "malformed_json",
    "unknown_fields",
    "png_integrity",
)


def main(extended_test_result: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(extended_test_result, dict):
        logger.error("Extended QR Code API test result is missing or invalid")
        return {
            "finished_successful": "false",
            "error_message": "Extended QR Code API test result is missing or invalid",
            "skipped": [],
        }

    errors: list[str] = []
    upstream_error = extended_test_result.get("error_message")
    if extended_test_result.get("finished_successful") != "true":
        errors.append(
            upstream_error if isinstance(upstream_error, str) and upstream_error.strip()
            else "Extended QR Code API test did not report success"
        )
        if "checks" not in extended_test_result:
            logger.error("Extended QR Code API test did not produce a check report")
            return {
                "finished_successful": "false",
                "error_message": errors[0],
                "skipped": [],
            }

    for field in ("container_id", "container_name"):
        value = extended_test_result.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} is missing or invalid")

    checks = extended_test_result.get("checks")
    if isinstance(checks, list):
        seen: set[str] = set()
        for check in checks:
            if not isinstance(check, dict) or not isinstance(check.get("name"), str) or not check["name"].strip():
                errors.append("Invalid check entry")
                continue
            name = check["name"]
            if name in seen:
                errors.append(f"Duplicate check: {name}")
            seen.add(name)
            status = check.get("status")
            if status != "passed":
                detail = check.get("error") or check.get("reason")
                message = f"Check {name}: {status if isinstance(status, str) and status else 'invalid status'}"
                if isinstance(detail, str) and detail.strip():
                    message += f" ({detail})"
                errors.append(message)
        for name in REQUIRED_CHECKS:
            if name not in seen:
                errors.append(f"Missing required check: {name}")
    else:
        errors.append("Extended QR Code API checks are missing or invalid")

    skipped = extended_test_result.get("skipped")
    if not isinstance(skipped, list):
        errors.append("Skipped-check information is missing or invalid")
        skipped = []
    elif any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not item["name"].strip()
        or not isinstance(item.get("reason"), str)
        or not item["reason"].strip()
        for item in skipped
    ):
        errors.append("Skipped-check information contains an invalid entry")

    if errors:
        logger.error("Extended QR Code API test evaluation failed")
        return {
            "finished_successful": "false",
            "error_message": "; ".join(errors),
            "skipped": skipped,
        }

    logger.info("Extended QR Code API test succeeded with %s explicitly skipped checks", len(skipped))
    return {"finished_successful": "true", "error_message": "", "skipped": skipped}
