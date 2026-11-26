Repo: https://github.com/FaolanBig/pkpass_builder_api_host
Base Image: ghcr.io/faolanbig/pkpass-builder-api-host

## Evaluating the smoke test

Add `evaluate_pkpass_smoke_test.py` as the final flow step and map its
`smoke_test_result` input to the smoke-test step's full result, for example
`results.<smoke_test_step_id>`. Use the actual step ID rather than the
placeholder. This remains the smoke-test result even if cleanup runs between
the test and the final step.

The evaluator checks the reported health, authentication, and PKPass results
and returns `finished_successful` as `"true"` or `"false"` with an
`error_message`. A failed evaluation is returned as data; it does not mark the
Windmill flow as failed. The evaluator does not assess container cleanup.

The final step can only evaluate results that reach it. Configure flow error
handling and cleanup separately for steps that raise exceptions or are skipped.

## Extended PKPass test

Run `pkpass_extended_test.py` after creating the API container and pass it the
creation step's `container_id`. Like the smoke test, it obtains the API key
from the Windmill variable `f/Image_Testing/pkpass_api_key` and uses Docker
exec to reach the API at `127.0.0.1:8000` inside the container; no port needs
to be published. `timeout_seconds` controls the health-check wait. The
container must have Python and Pillow, as the API host image does. Set
`PKPASS_SIGNING_MODE=unsigned` on the container if signing certificates are
not available.

The result contains `finished_successful`, `error_message`, and individual
`checks` with pass/fail details. It checks API authentication and input
validation, ZIP and image integrity, pass and vCard fields, optional fields,
aliases, profile thumbnails, and unique serial numbers. If present, a manifest
is checked against the archive files. Signature verification, actual Apple
Wallet installation, and decoding the generated QR image are explicitly
reported as skipped. An unsigned package cannot be installed in Apple Wallet,
so a successful result is not proof of device compatibility or a valid
signature. The existing smoke-test evaluator expects the smoke-test result
shape and should not be used to evaluate this extended report.

To evaluate the extended report, add `evaluate_pkpass_extended_test.py` as the
final flow step and map `extended_test_result` to the extended-test step's full
result, for example `results.<extended_test_step_id>`. Use the actual step ID.
The evaluator requires every current extended check to pass and preserves the
separate `skipped` list in its result. It returns failures as data rather than
failing the Windmill flow, and does not assess cleanup. Configure flow error
handling separately for steps that raise exceptions or are skipped. If the
extended test's check names change, update the evaluator's required list.