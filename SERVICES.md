# Floci service capabilities

These are observed real boto3 results, not SDK mocks or a service-health checklist.
Tested with Floci 2.4.0, image digest
`sha256:5ee85db604c4aa74ac76e07ea5cc83086f37bb472bf3dbb97e34019e48efae9c`,
boto3 1.44.9 and region `us-east-1`. Credentials were supplied only through
process environment variables. Resource names were unique and probe resources
were deleted; deletion was checked through read/list calls.

`works` means the listed operations and stated payload assertions passed, not
complete AWS compatibility. `partial` means management APIs passed but the
relevant data plane was not verified. `unsupported` would mean tested operations
were rejected as unimplemented; none of these probes returned that result.

| Service | Operations tested | Status | Notes on errors and limits |
|---|---|---|---|
| CloudWatch Logs | Create/describe/delete log group and stream; put/get log events; put/describe/delete subscription and metric filters; metric statistics; put/describe/delete alarm | works | No API errors. Event round-trip, subscription delivery through Firehose to S3, ERROR metric samples and automatic alarm transition verified. CloudWatch monitoring API also tested. |
| Kinesis Firehose | Create/describe/list/delete delivery stream; put_record; put_record_batch; verify S3 delivery | works | No API errors. Single/batch DirectPut and subscription gzip-envelope delivery verified in S3; 60-second buffering. |
| S3 | Create/head/list/delete bucket; put/get/list/delete object; exact payload readback | works | No API errors. Bucket/object CRUD and exact payload verified. |
| OpenSearch | List/create/describe/configure-read/delete domain; verify deletion | partial | No API errors. Domain management CRUD tested only. Created=False, Processing=True. Search/index data plane and cluster readiness not tested; no claim of a working search backend. |
| IAM | Create/get/delete role; put/get/list/delete inline role policy | works | No API errors. Role and inline-policy CRUD verified; authorization enforcement, STS and cross-account behavior not tested. |
| SNS | Create/get/list/delete topic; subscribe/unsubscribe; publish; verify SQS payload | works | No API errors. Topic CRUD, subscription and publish-to-SQS payload verified; other delivery protocols not tested. |
| SQS | Create/get attributes/list/delete queue; send/receive/delete message; verify removal | works | No API errors. Queue CRUD and send/receive/delete payload verified; FIFO and DLQ behavior not tested. |
| Lambda | Create/get/configuration/list/delete function; synchronous Python invocation; verify response | works | No API errors. Real Python 3.12 invocation and exact response verified; event-source mappings not tested. |
| WAFv2 | Create/get/list/delete regional Web ACL; lock-token handling; verify deletion | partial | No API errors. Regional Web ACL management CRUD verified; request filtering, associations and WAF logging delivery not tested. |
| ELBv2 | Create/describe/delete ALB and HTTP listener; supporting VPC/subnet CRUD; verify deletion | partial | No API errors. ALB/listener management CRUD verified with real supporting VPC/subnets; HTTP forwarding, access-log delivery and targets not tested. |

The project uses only the services marked `works`: Logs, Firehose, S3 and IAM,
plus the CloudWatch metric/alarm API explicitly verified with the Logs probes.
SNS, SQS and Lambda passed their listed probes but are not required by the pattern.
OpenSearch, WAFv2 and ELBv2 are excluded. Their `partial` labels describe coverage
limits, not observed failures of their management APIs.

## Pipeline checks

- Logs -> subscription filter -> Firehose -> S3: emitted messages recovered from
  gzip subscription envelopes, including both INFO and ERROR messages.
- ERROR metric filter -> CloudWatch statistics: one error counted; INFO did not
  increment the count.
- Single-metric alarm: configured for at least one error per 60-second period;
  an automatic ALARM transition was observed without `set_alarm_state`.
- Context teardown: resource absence checked after a deliberate caller exception.
- No calls against real AWS were made. OpenSearch indexing/search, WAF traffic
  filtering/log delivery, and ALB HTTP forwarding/access logs were not tested.
