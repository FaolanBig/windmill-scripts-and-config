#requirements:
#docker==7.1.0
#wmill

import inspect
import json
import logging
import os
from typing import Any

import docker
import wmill
from docker.errors import DockerException


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def run_inside_container(timeout_seconds):
    import base64
    import hashlib
    import io
    import json
    import os
    import time
    import urllib.error
    import urllib.request
    import zipfile

    from PIL import Image

    key = os.environ["PKPASS_TEST_API_KEY"]
    base_url = "http://127.0.0.1:8000"
    payload = {
        "givenName": "Ada",
        "surname": "Lovelace",
        "academicDegree": "PhD",
        "company": "Analytical Engines",
        "jobPosition": "Researcher",
        "showJobPosition": True,
        "email": "ada@example.org",
        "phoneNumber": "+1 555 0100",
        "department": "Computing",
        "street": "1 Main St",
        "postalCode": "SW1A 1AA",
        "city": "London",
        "country": "UK",
    }
    checks = []

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def check(name, action):
        try:
            action()
        except Exception as error:
            checks.append({"name": name, "status": "failed", "error": str(error)})
        else:
            checks.append({"name": name, "status": "passed"})

    def request(method, path, body=None, api_key=None, raw=None):
        headers = {}
        data = raw
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = "application/json"
        if api_key is not None:
            headers["X-API-Key"] = api_key
        req = urllib.request.Request(
            base_url + path, data=data, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(req, timeout=3 if path == "/health" else 15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read(10_000_001)

    def expect_status(expected, method, path, body=None, api_key=None, raw=None):
        status, headers, data = request(method, path, body, api_key, raw)
        require(status == expected, f"Expected HTTP {expected}, got {status}")
        return headers, data

    def archive_for(body):
        headers, data = expect_status(200, "POST", "/passes", body, key)
        content_type = headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        require(content_type == "application/vnd.apple.pkpass", "Incorrect content type")
        require(len(data) <= 10_000_000, "PKPass exceeds 10 MB")
        require(zipfile.is_zipfile(io.BytesIO(data)), "Response is not a ZIP archive")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            require(len(names) == len(set(names)), "Archive contains duplicate filenames")
            require(all(not name.startswith("/") and ".." not in name.split("/") for name in names),
                    "Archive contains an unsafe filename")
            require(sum(entry.file_size for entry in archive.infolist()) <= 20_000_000,
                    "Uncompressed archive exceeds 20 MB")
            require(archive.testzip() is None, "Archive CRC validation failed")
            require({"pass.json", "icon.png", "icon@2x.png", "qr.png"} <= set(names),
                    "Required pass files are missing")
            files = {name: archive.read(name) for name in names if not name.endswith("/")}
        for name in ("icon.png", "icon@2x.png", "qr.png"):
            with Image.open(io.BytesIO(files[name])) as image:
                require(image.format == "PNG", f"{name} is not PNG")
                image.verify()
        for name, dimensions in (("icon.png", (29, 29)), ("icon@2x.png", (58, 58))):
            with Image.open(io.BytesIO(files[name])) as image:
                require(image.size == dimensions, f"{name} has unexpected dimensions")
        if "manifest.json" in files:
            manifest = json.loads(files["manifest.json"])
            require(isinstance(manifest, dict), "Manifest is not an object")
            expected = set(files) - {"manifest.json", "signature"}
            require(set(manifest) == expected, "Manifest file list does not match archive")
            for name in expected:
                require(manifest[name] == hashlib.sha1(files[name]).hexdigest(),
                        f"Manifest digest mismatch for {name}")
        data = json.loads(files["pass.json"])
        require(isinstance(data, dict), "pass.json is not an object")
        return data, files

    def field_map(pass_data, section):
        generic = pass_data["generic"]
        fields = generic[section]
        require(isinstance(fields, list), f"{section} is not a list")
        result = {}
        for field in fields:
            require(isinstance(field, dict) and isinstance(field.get("key"), str),
                    f"{section} contains an invalid field")
            require(field["key"] not in result, f"{section} contains duplicate keys")
            result[field["key"]] = field.get("value")
        return result

    def verify_pass(pass_data, position=True, phone=True, degree=True):
        require(pass_data.get("formatVersion") == 1, "Invalid formatVersion")
        for name in ("passTypeIdentifier", "serialNumber", "teamIdentifier",
                     "organizationName", "description"):
            require(isinstance(pass_data.get(name), str) and bool(pass_data[name].strip()),
                    f"Missing or invalid {name}")
        for name in ("foregroundColor", "backgroundColor", "labelColor"):
            require(isinstance(pass_data.get(name), str) and pass_data[name].startswith("rgb("),
                    f"Missing or invalid {name}")
        expected_name = "PhD Ada Lovelace" if degree else "Ada Lovelace"
        require(field_map(pass_data, "primaryFields").get("name") == expected_name,
                "Display name does not match request")
        secondary = field_map(pass_data, "secondaryFields")
        auxiliary = field_map(pass_data, "auxiliaryFields")
        back = field_map(pass_data, "backFields")
        field_map(pass_data, "headerFields")
        require(back.get("email") == payload["email"], "Email does not match request")
        require(back.get("address") == "1 Main St\nSW1A 1AA London\nUK",
                "Address does not match request")
        require(back.get("phone") == payload["phoneNumber"] if phone else "phone" not in back,
                "Phone field does not match request")
        address_fields = auxiliary if position else secondary
        require(address_fields.get("street") == "1 Main St", "Street does not match request")
        require(address_fields.get("city") == "SW1A 1AA London", "City does not match request")
        require(auxiliary.get("country") == "UK", "Country does not match request")
        require(secondary.get("position") == "Researcher" if position else "position" not in secondary,
                "Position front field is incorrect")
        require(back.get("position") == "Researcher" if position else "position" not in back,
                "Position back field is incorrect")
        barcodes = pass_data.get("barcodes")
        require(isinstance(barcodes, list) and len(barcodes) > 0, "No barcode")
        barcode = barcodes[0]
        require(barcode.get("format") == "PKBarcodeFormatQR", "Barcode is not QR")
        require(barcode.get("messageEncoding") == "utf-8", "Incorrect barcode encoding")
        vcard = barcode.get("message")
        require(isinstance(vcard, str), "Barcode message is missing")
        lines = vcard.splitlines()
        require(lines[0:2] == ["BEGIN:VCARD", "VERSION:3.0"] and lines[-1:] == ["END:VCARD"],
                "Invalid vCard envelope")
        for line in (f"FN:{expected_name}", "ORG:Analytical Engines",
                     "EMAIL;TYPE=WORK:ada@example.org",
                     "ADR;TYPE=WORK:;;1 Main St;London;;SW1A 1AA;UK"):
            require(any(item == line or (line.startswith("ORG:") and item.startswith(line + ";"))
                        for item in lines), "vCard contact data does not match request")
        require(("TEL;TYPE=WORK,VOICE:+1 555 0100" in lines) == phone,
                "vCard phone does not match request")
        return lines

    def health():
        deadline = time.monotonic() + max(timeout_seconds, 1)
        last_error = "no response"
        while time.monotonic() < deadline:
            try:
                _, data = expect_status(200, "GET", "/health")
                require(json.loads(data) == {"status": "ok"}, "Unexpected health response")
                return
            except (OSError, ValueError) as error:
                last_error = str(error)
                time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise ValueError(f"Health check timed out: {last_error}")

    check("health", health)
    if checks[-1]["status"] == "passed":
        check("missing_api_key", lambda: expect_status(401, "POST", "/passes", payload))
        check("wrong_api_key", lambda: expect_status(401, "POST", "/passes", payload, key + "-incorrect"))

        def standard_pass():
            pass_data, _ = archive_for(payload)
            lines = verify_pass(pass_data)
            require("TITLE:Researcher" in lines, "vCard position is missing")
            require("N:Lovelace;Ada;;PhD;" in lines, "vCard name is incorrect")

        check("full_contact_and_archive", standard_pass)

        def hidden_position():
            pass_data, _ = archive_for({**payload, "showJobPosition": False})
            lines = verify_pass(pass_data, position=False)
            require("TITLE:Researcher" in lines, "Hidden position missing from vCard")

        check("hidden_position", hidden_position)

        def optional_fields():
            body = {**payload, "academicDegree": "N/A", "phoneNumber": "N/A"}
            body.pop("jobPosition")
            pass_data, _ = archive_for(body)
            lines = verify_pass(pass_data, position=False, phone=False, degree=False)
            require(not any(line.startswith("TITLE:") for line in lines), "Unexpected vCard position")

        check("optional_fields_and_na", optional_fields)

        def snake_case_aliases():
            aliases = {
                "given_name": payload["givenName"], "surname": payload["surname"],
                "academic_degree": payload["academicDegree"], "company": payload["company"],
                "job_position": payload["jobPosition"], "show_job_position": True,
                "email": payload["email"], "phone_number": payload["phoneNumber"],
                "department": payload["department"], "street": payload["street"],
                "postal_code": payload["postalCode"], "city": payload["city"],
                "country": payload["country"],
            }
            pass_data, _ = archive_for(aliases)
            verify_pass(pass_data)

        check("snake_case_aliases", snake_case_aliases)

        def unicode_and_vcard_escaping():
            body = {**payload, "givenName": "Zoë; Test", "surname": "O'Connor, Jr"}
            pass_data, _ = archive_for(body)
            require(field_map(pass_data, "primaryFields").get("name") == "PhD Zoë; Test O'Connor, Jr",
                    "Unicode name does not match request")
            lines = pass_data["barcodes"][0]["message"].splitlines()
            require(r"FN:PhD Zoë\; Test O'Connor\, Jr" in lines,
                    "vCard full name is not escaped correctly")
            require(r"N:O'Connor\, Jr;Zoë\; Test;;PhD;" in lines,
                    "vCard structured name is not escaped correctly")

        check("unicode_and_vcard_escaping", unicode_and_vcard_escaping)

        def profile_picture():
            image_bytes = io.BytesIO()
            Image.new("RGB", (120, 80), "purple").save(image_bytes, format="PNG")
            picture = base64.b64encode(image_bytes.getvalue()).decode("ascii")
            pass_data, files = archive_for({**payload, "profilePicture": picture})
            verify_pass(pass_data)
            for name, size in (("thumbnail.png", 90), ("thumbnail@2x.png", 180),
                               ("thumbnail@3x.png", 270)):
                require(name in files, f"Missing {name}")
                with Image.open(io.BytesIO(files[name])) as image:
                    require(image.format == "PNG" and image.size == (size, size),
                            f"Invalid {name} dimensions or format")
                    image.load()
                    require(image.convert("RGB").getpixel((size // 2, size // 2)) == (128, 0, 128),
                            f"{name} does not contain the supplied image")

        check("profile_picture", profile_picture)
        for field, value in (("givenName", ""), ("surname", "x" * 257),
                             ("email", "not-an-email"), ("showJobPosition", "false"),
                             ("phoneNumber", ""),
                             ("profilePicture", base64.b64encode(b"not an image").decode("ascii"))):
            check(f"reject_invalid_{field}",
                  lambda field=field, value=value: expect_status(
                      422, "POST", "/passes", {**payload, field: value}, key
                  ))
        missing_name = dict(payload)
        missing_name.pop("givenName")
        check("reject_missing_name", lambda: expect_status(422, "POST", "/passes", missing_name, key))
        check("reject_malformed_json", lambda: expect_status(422, "POST", "/passes", api_key=key, raw=b"{"))

        def serial_numbers():
            first, _ = archive_for(payload)
            second, _ = archive_for(payload)
            require(first.get("serialNumber") != second.get("serialNumber"),
                    "Generated passes have the same serial number")

        check("unique_serial_numbers", serial_numbers)
    else:
        checks.append({"name": "remaining_checks", "status": "skipped",
                       "reason": "Health check did not pass"})

    failed = sum(item["status"] == "failed" for item in checks)
    return {
        "finished_successful": "false" if failed else "true",
        "error_message": f"{failed} check(s) failed" if failed else "",
        "checks": checks,
        "skipped": [
            {"name": "signature_verification", "reason": "Apple signing certificates are not available"},
            {"name": "apple_wallet_installation", "reason": "Requires a signed pass and Apple device"},
            {"name": "qr_image_decoding", "reason": "No QR decoder is assumed available in the container"},
        ],
    }


def main(container_id: str, timeout_seconds: int = 60) -> dict[str, Any]:
    if not container_id or not container_id.strip():
        return {"finished_successful": "false", "error_message": "container_id is required"}
    if timeout_seconds < 1:
        return {"finished_successful": "false", "error_message": "timeout_seconds must be at least 1"}

    try:
        api_key = wmill.get_variable("f/Image_Testing/pkpass_api_key")
    except Exception:
        logger.error("Failed to retrieve the PKPass API key from Windmill")
        return {"finished_successful": "false", "error_message": "Could not retrieve PKPass API key"}
    if not isinstance(api_key, str) or not api_key:
        return {"finished_successful": "false", "error_message": "PKPass API key is missing"}

    client = None
    try:
        client = docker.DockerClient(
            base_url=os.environ.get("DOCKER_HOST") or "tcp://docker-test-daemon:2375",
            tls=False, timeout=max(30, timeout_seconds + 300),
        )
        client.ping()
        container = client.containers.get(container_id)
        container.reload()
        if container.status != "running":
            return {"finished_successful": "false", "error_message": f"Container is not running: {container.status}"}
        logger.info("Running extended PKPass tests for container %s", container_id)
        source = inspect.getsource(run_inside_container)
        source += f"\nimport json\nprint(json.dumps(run_inside_container({timeout_seconds})))\n"
        result = container.exec_run(
            ["python", "-c", source],
            environment={"PKPASS_TEST_API_KEY": api_key},
            stdout=True, stderr=True,
        )
        output = result.output.decode("utf-8", errors="replace") if isinstance(result.output, bytes) else ""
        if result.exit_code != 0:
            logger.error("Extended PKPass test process failed with exit code %s", result.exit_code)
            return {
                "finished_successful": "false",
                "error_message": (
                    f"Test process failed with exit code {result.exit_code}; "
                    "verify the container has Python and Pillow"
                ),
            }
        try:
            report = json.loads(output)
        except json.JSONDecodeError:
            return {"finished_successful": "false", "error_message": "Test process returned invalid JSON"}
        if not isinstance(report, dict) or report.get("finished_successful") not in ("true", "false"):
            return {"finished_successful": "false", "error_message": "Test process returned an invalid report"}
        report["container_id"] = container_id
        report["container_name"] = container.name or container_id
        logger.info("Extended PKPass test finished: %s", report["finished_successful"])
        return report
    except DockerException as error:
        logger.error("Docker operation failed during PKPass test (%s)", type(error).__name__)
        return {"finished_successful": "false", "error_message": f"Docker operation failed: {error}"}
    finally:
        if client is not None:
            client.close()
