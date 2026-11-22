# Implementation workflow

## Prompt used

The implementation followed this task prompt (project-local excerpt):

> Goal: a generic logging pipeline pattern. Application logs go to CloudWatch
> Logs, a subscription filter sends them to Firehose, Firehose delivers to S3,
> and a metric filter plus alarm covers error rates. If a link in that chain is
> unsupported, build the closest working variant and document the gap in the README.

Additional requirements: probe ten services with real boto3 calls first; use
only verified services; Python source and pytest integration tests; a digest-pinned
Floci Compose service; Make targets up/down/test/lint; a GitHub Actions job named
test; an MIT license; capability results and honest documentation. Use process-only
dummy AWS credentials, publish no private infrastructure or personal information,
and make all changes through a feature PR with green CI and a squash merge.

## Built

- Preserved the existing README opening and repository history; all changes were
  developed on a feature branch, not committed or pushed directly to main.
- Probed all ten requested services against the running emulator. All listed
  management calls passed. OpenSearch, WAFv2 and ELBv2 remain partial because their
  relevant data planes were not verified; the pattern excludes them.
- Implemented the complete Logs -> subscription -> Firehose -> S3 chain. Readback
  recovers actual gzip log envelopes, not fabricated or directly uploaded payloads.
- Added an ERROR metric filter and a naturally evaluated single-metric alarm for
  an error count per minute. No forced state changes or metric mocks are used.
- Added isolated names, context-managed cleanup, explicit local endpoint guards,
  environment-only credentials, and checks that resources are removed after an
  intentional caller exception.
- Added digest-matched Compose/CI services without Docker socket mounts, plus
  Make targets, Python dependency pins, ruff configuration and integration tests.

## What failed and how it was fixed

- The first test intentionally failed because the logging module did not exist.
  The implementation was then added and the real end-to-end test passed.
- The first ruff run found import ordering and modernization issues. Ruff's safe
  fixes and formatter resolved them; subsequent lint runs passed.
- The first Make invocation failed because GNU Make was absent. Installing Make
  in the user tool directory resolved that prerequisite; no repository workaround
  or elevated system change was used.
- Alarm evaluation can precede S3 delivery, and its state can later return to OK.
  The alarm assertion is run before waiting on Firehose's longer buffer to avoid
  missing the observed transition.
- Firehose's newline-separated gzip payloads require reading individual members;
  the S3 reader tolerates those separators and validates complete gzip members.
  This was handled in the initial implementation, not discovered as a failed test.

## Verification

- All ten capability probes used actual boto3 requests with unique resources and
  cleanup. SNS-to-SQS payloads, S3 contents, Firehose delivery, and a real Python
  Lambda result were checked, not just HTTP response codes.
- The initial end-to-end pipeline test passed against the existing emulator.
- The expanded suite passed eight tests, including the automatic alarm, INFO/error
  discrimination, endpoint/credential guards and failure-path cleanup.
- A separate fresh Compose emulator using the exact pinned digest, without a
  Docker socket, passed `make lint` and all eight tests through `make test`.
  The temporary Compose instance was removed afterward; the existing emulator
  was left running.
- Real AWS, IAM enforcement/role propagation, OpenSearch indexing, WAF traffic
  filtering/log delivery, ALB forwarding/access logs and alarm notifications were
  not tested. CloudWatch metric samples have no delete API and may remain in the
  emulator until its data is reset; named probe resources were deleted.

## PR follow-up convention

After a merged PR, the next PR appends one line describing what was built, what
broke and how it was fixed. CI corrections for this PR belong in this record
before merge; no post-merge commit to main is permitted.
