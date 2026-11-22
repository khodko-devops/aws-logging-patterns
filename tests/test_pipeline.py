"""Real Floci integration tests: no mocks and no calls to real AWS."""

import importlib.util
import time

import pytest
from botocore.exceptions import ClientError


@pytest.fixture(scope="module")
def pipeline():
    assert importlib.util.find_spec("logging_pattern"), "logging pipeline is not implemented"
    from logging_pattern import Pipeline

    with Pipeline() as instance:
        instance.emit(["INFO request completed", "ERROR request failed"])
        yield instance


def test_alarm_evaluates_error_metric(pipeline):
    # Observe the transition before waiting for the longer Firehose buffer.
    deadline = time.monotonic() + 90
    while pipeline.alarm()["StateValue"] != "ALARM":
        assert time.monotonic() < deadline, "Floci did not evaluate the error-count alarm"
        time.sleep(1)


def test_pipeline_round_trip(pipeline):
    records = pipeline.wait_for_records(timeout=90)
    assert [event["message"] for record in records for event in record["logEvents"]] == [
        "INFO request completed",
        "ERROR request failed",
    ]
    assert all(record["messageType"] == "DATA_MESSAGE" for record in records)
    assert pipeline.error_count() == 1
    alarm = pipeline.alarm()
    assert alarm["MetricName"] == "Errors"
    assert alarm["Threshold"] == 1
    assert alarm["Period"] == 60
    assert alarm["Namespace"] == pipeline.namespace
    filters = pipeline.logs.describe_subscription_filters(logGroupName=pipeline.name)[
        "subscriptionFilters"
    ]
    assert len(filters) == 1
    assert filters[0]["destinationArn"].endswith("/" + pipeline.name)


def test_info_event_does_not_count_as_error(pipeline):
    pipeline.emit(["INFO another successful request"])
    assert pipeline.error_count() == 1


def test_context_cleans_up_after_failure():
    from logging_pattern import Pipeline

    instance = Pipeline()
    with pytest.raises(RuntimeError, match="exercise cleanup"):
        with instance:
            raise RuntimeError("exercise cleanup")
    assert not instance.logs.describe_log_groups(logGroupNamePrefix=instance.name)["logGroups"]
    assert instance.name not in instance.firehose.list_delivery_streams()["DeliveryStreamNames"]
    assert not instance.metrics.describe_alarms(AlarmNames=[instance.name])["MetricAlarms"]
    assert instance.name not in [b["Name"] for b in instance.s3.list_buckets()["Buckets"]]
    for suffix in ("logs", "firehose"):
        with pytest.raises(ClientError) as error:
            instance.iam.get_role(RoleName=instance.name + "-" + suffix)
        assert error.value.response["Error"]["Code"] == "NoSuchEntity"


@pytest.mark.parametrize("endpoint", ["", "https://example.com", "http://example.com"])
def test_requires_explicit_local_endpoint(monkeypatch, endpoint):
    from logging_pattern import Pipeline

    monkeypatch.setenv("AWS_ENDPOINT_URL", endpoint)
    with pytest.raises(ValueError, match="local HTTP endpoint"):
        Pipeline()


def test_requires_environment_credentials(monkeypatch):
    from logging_pattern import Pipeline

    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    with pytest.raises(ValueError, match="environment variables"):
        Pipeline()
