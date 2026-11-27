# QR Code Generator image testing

This directory contains Windmill scripts for testing the
[QR Code API Server](https://github.com/FaolanBig/qr-code_api_server/tree/deployment_publish_docker_images_auto).

- `qr_code_generator_smoke_test.py` waits for `/healthz`, verifies unauthenticated access is rejected, and creates a text QR code.
- `qr_code_generator_extended_test.py` exercises authentication, public probes, all QR types, image options, logos, multipart uploads, validation, and PNG integrity.
- `evaluate_qr_code_generator_smoke_test.py` validates the smoke-test report.
- `evaluate_qr_code_generator_extended_test.py` requires every explicit extended check to pass and preserves skipped checks.

The tests retrieve `f/Image_Testing/qr_code_api_key` from Windmill. The container must define `API_KEY` (or be passed the API key in `ct_environment`) and listen on port `8080`, or set `LISTEN_ADDRESS` to a host-port value such as `:8081`.

Reuse the repository's generic Docker container creation and removal scripts. The test scripts use Docker exec and do not require a published API port.
