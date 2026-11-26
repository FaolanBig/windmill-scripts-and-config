import logging
import os
from typing import Any


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)


def main(smoke_test_result: dict[str, Any] | None = None) -> dict[str, str]:
    if not isinstance(smoke_test_result, dict):
        logger.error("PKPass smoke-test result is missing or invalid")
        return {
            "finished_successful": "false",
            "error_message": "PKPass smoke-test result is missing or invalid",
        }

    if smoke_test_result.get("finished_successful") != "true":
        error = smoke_test_result.get("error_message")
        logger.error("PKPass smoke test did not report success")
        return {
            "finished_successful": "false",
            "error_message": error if isinstance(error, str) and error else
            "PKPass smoke test did not report success",
        }

    errors = []
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

    status = smoke_test_result.get("unauthenticated_status")
    if type(status) is not int or status != 401:
        errors.append("unauthenticated HTTP status is not 401")

    apple_pass = smoke_test_result.get("apple_pass")
    if not isinstance(apple_pass, dict):
        errors.append("apple_pass result is missing or invalid")
    else:
        if type(apple_pass.get("http_status")) is not int or apple_pass["http_status"] != 200:
            errors.append("PKPass HTTP status is not 200")
        content_type = apple_pass.get("content_type")
        if not isinstance(content_type, str) or "application/vnd.apple.pkpass" not in content_type:
            errors.append("PKPass content type is invalid")
        size = apple_pass.get("size_bytes")
        if type(size) is not int or size <= 0:
            errors.append("PKPass size is not a positive integer")
        for field in ("is_zip", "has_pass_json", "crc_valid"):
            if apple_pass.get(field) is not True:
                errors.append(f"PKPass {field} is not true")

    if errors:
        logger.error("PKPass smoke-test result failed validation")
        return {
            "finished_successful": "false",
            "error_message": "; ".join(errors),
        }

    logger.info("PKPass smoke test succeeded")
    return {"finished_successful": "true", "error_message": ""}
