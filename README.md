# aws-logging-patterns
Generic CloudWatch → Firehose → S3 logging pattern

[![CI](https://github.com/khodko-devops/aws-logging-patterns/actions/workflows/ci.yml/badge.svg)](https://github.com/khodko-devops/aws-logging-patterns/actions/workflows/ci.yml)

## What it does

```text
Application messages -> CloudWatch Logs -> subscription filter -> Firehose -> S3
                                  |
                                  +-> ERROR metric filter -> CloudWatch alarm
```

`src/logging_pattern.py` contains a small boto3 `Pipeline` context manager. It
creates uniquely named resources, provisions delivery roles and inline policies,
and removes its resources on exit, including when a caller raises an exception.
The tests emit application messages into Logs and recover the same messages from
gzip subscription envelopes delivered to S3. There is no direct-to-S3 fallback:
the entire requested delivery chain passed against the pinned Floci image.

The error-rate signal is a **count per 60-second period**, not an error percentage.
An `ERROR` filter emits the `Errors` metric; the alarm uses Sum >= 1 over one
period, treating missing data as not breaching. The tests observe a real automatic
alarm transition; they do not force alarm state. Notifications are not configured.

## Run in two commands

Prerequisites: Docker with Compose v2, Python 3.12 or newer with venv, make, and
network access to install the pinned Python packages and Floci image.

```sh
make up
make test
```

`make up` starts a disposable, loopback-only Floci instance and waits for health.
`make test` creates a virtual environment, installs dependencies, and runs real
boto3 integration tests. Dummy credentials are supplied to that process through
environment variables only; no AWS credential file is created. The target name
supplies the dummy credential value. Metadata and shared credential/config files
are disabled for the test process. First-run delivery takes about a minute because
Firehose buffers records. `make lint` runs ruff; `make down` removes only this
Compose project's container and network.

If a compatible Floci instance is already running, use `make test` without starting
another instance. To use a different local port, run `FLOCI_PORT=14566 make up` and
pass a matching local `AWS_ENDPOINT_URL` to `make test`. The source requires an
explicit loopback HTTP endpoint and environment credentials, so it cannot
accidentally fall back to a real AWS endpoint or a shared AWS profile.

## Use the pattern

With the same environment as the test command, the core interface is:

```python
from logging_pattern import Pipeline

with Pipeline() as pipeline:
    pipeline.emit(["INFO request completed", "ERROR request failed"])
    records = pipeline.wait_for_records(timeout=90)
    print(records)
    print(pipeline.error_count())
```

Set `PYTHONPATH=src` when using this interface outside pytest. The example is
**ephemeral**: leaving the context deletes the archive and all other resources.
Await delivery before exit; pending Firehose records are discarded during teardown.
This is a runnable pattern and test harness, not a persistent deployment tool.

## Tested on Floci, not on real AWS

See [SERVICES.md](SERVICES.md) for all ten service probes, exact operations,
coverage limits and observed results. The pipeline uses only verified services.

Known differences and limits:

- Floci subscription delivery is synchronous during ingestion; a destination
  failure may not make log ingestion fail. Tests therefore verify S3 payloads,
  not just a successful `put_log_events` response.
- Firehose appends newline separators between record payloads in this image.
  The reader handles gzip members with those separators; this is not a claim
  that AWS inserts separators.
- The single-metric alarm was observed evaluating automatically. This pattern
  does not exercise metric math, percentage error rates, notification delivery,
  delayed ingestion, or production alarm tuning.
- IAM role/policy CRUD passed. Permission enforcement, role-assumption timing,
  least-privilege completeness and real AWS authorization were not validated.
- OpenSearch management operations passed while the domain was still processing;
  indexing/search and readiness were not verified. WAFv2 Web ACL CRUD and ELBv2
  ALB/listener CRUD passed, but their traffic and logging data planes were not
  tested. These three partially verified services are excluded from the pattern.
- No tested management operation returned an unsupported-service error. This
  does not mean every operation in these services is implemented.
- SNS-to-SQS delivery and a real Python Lambda invocation passed the local
  capability probes, but they are not dependencies of the pattern or CI tests.
- The Compose and CI image is pinned by digest, with no Docker socket mount,
  persistent data volume, real AWS credentials or external service dependencies.
  Capability probes for Lambda and OpenSearch used the already running emulator;
  CI exercises only the logging pipeline.

## CI and project files

The GitHub Actions job is named `test`. It starts the same pinned Floci image as
a service container, then runs `make lint` and `make test` using Python 3.12.
All SDK calls in the tests use `AWS_ENDPOINT_URL`; no mocks or real AWS calls are
used. Test resources have unique names and are cleaned up.

- `src/`: the context-managed logging pattern.
- `tests/`: payload, metric, alarm, safety and cleanup integration checks.
- `SERVICES.md`: observed capability matrix.
- `WORKFLOW.md`: implementation prompt, verification and fixes.

Licensed under the [MIT License](LICENSE).
