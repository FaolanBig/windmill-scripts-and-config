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