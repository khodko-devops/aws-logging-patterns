"""A disposable CloudWatch Logs -> Firehose -> S3 pattern for local emulators."""

import json
import os
import time
import uuid
import zlib
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import boto3
from botocore.config import Config


class Pipeline:
    """Provision isolated resources and always remove them on context exit."""

    def __init__(self):
        endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1"):
            raise ValueError("AWS_ENDPOINT_URL must be an explicit local HTTP endpoint")
        if not os.environ.get("AWS_ACCESS_KEY_ID") or not os.environ.get("AWS_SECRET_ACCESS_KEY"):
            raise ValueError("Supply dummy AWS credentials through environment variables")
        self.name = "logging-" + uuid.uuid4().hex[:12]
        self.namespace = self.name
        self._cleanup = ExitStack()
        session = boto3.Session()
        config = Config(
            connect_timeout=5,
            read_timeout=15,
            retries={"total_max_attempts": 2, "mode": "standard"},
            s3={"addressing_style": "path"},
        )
        self.logs, self.firehose, self.s3, self.iam, self.metrics = (
            session.client(service, endpoint_url=endpoint, config=config)
            for service in ("logs", "firehose", "s3", "iam", "cloudwatch")
        )

    def _role(self, suffix, principal, actions, resource):
        name = self.name + "-" + suffix
        trust = {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Principal": {"Service": principal}, "Action": "sts:AssumeRole"}
            ],
        }
        role = self.iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust))[
            "Role"
        ]
        self._cleanup.callback(self.iam.delete_role, RoleName=name)
        policy = {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": actions, "Resource": resource}],
        }
        self.iam.put_role_policy(
            RoleName=name, PolicyName="delivery", PolicyDocument=json.dumps(policy)
        )
        self._cleanup.callback(self.iam.delete_role_policy, RoleName=name, PolicyName="delivery")
        return role["Arn"]

    def __enter__(self):
        try:
            self._provision()
        except BaseException:
            self._cleanup.close()
            raise
        return self

    def _provision(self):
        self.s3.create_bucket(Bucket=self.name)
        self._cleanup.callback(self._delete_bucket)
        delivery_role = self._role(
            "firehose",
            "firehose.amazonaws.com",
            ["s3:PutObject", "s3:GetBucketLocation", "s3:ListBucket", "s3:AbortMultipartUpload"],
            [f"arn:aws:s3:::{self.name}", f"arn:aws:s3:::{self.name}/*"],
        )
        stream = self.firehose.create_delivery_stream(
            DeliveryStreamName=self.name,
            DeliveryStreamType="DirectPut",
            S3DestinationConfiguration={
                "RoleARN": delivery_role,
                "BucketARN": f"arn:aws:s3:::{self.name}",
                "Prefix": "application/",
                "CompressionFormat": "UNCOMPRESSED",
                "BufferingHints": {"SizeInMBs": 1, "IntervalInSeconds": 60},
            },
        )["DeliveryStreamARN"]
        self._cleanup.callback(self.firehose.delete_delivery_stream, DeliveryStreamName=self.name)
        deadline = time.monotonic() + 30
        while (
            self.firehose.describe_delivery_stream(DeliveryStreamName=self.name)[
                "DeliveryStreamDescription"
            ]["DeliveryStreamStatus"]
            != "ACTIVE"
        ):
            if time.monotonic() >= deadline:
                raise TimeoutError("Firehose did not become active")
            time.sleep(1)
        subscription_role = self._role(
            "logs",
            "logs.amazonaws.com",
            ["firehose:PutRecord", "firehose:PutRecordBatch"],
            stream,
        )
        self.logs.create_log_group(logGroupName=self.name)
        self._cleanup.callback(self.logs.delete_log_group, logGroupName=self.name)
        self.logs.create_log_stream(logGroupName=self.name, logStreamName="application")
        self.logs.put_subscription_filter(
            logGroupName=self.name,
            filterName="archive",
            filterPattern="",
            destinationArn=stream,
            roleArn=subscription_role,
        )
        self._cleanup.callback(
            self.logs.delete_subscription_filter, logGroupName=self.name, filterName="archive"
        )
        self.logs.put_metric_filter(
            logGroupName=self.name,
            filterName="errors",
            filterPattern="ERROR",
            metricTransformations=[
                {"metricName": "Errors", "metricNamespace": self.namespace, "metricValue": "1"}
            ],
        )
        self._cleanup.callback(
            self.logs.delete_metric_filter, logGroupName=self.name, filterName="errors"
        )
        self.metrics.put_metric_alarm(
            AlarmName=self.name,
            Namespace=self.namespace,
            MetricName="Errors",
            Statistic="Sum",
            Period=60,
            EvaluationPeriods=1,
            DatapointsToAlarm=1,
            Threshold=1,
            ComparisonOperator="GreaterThanOrEqualToThreshold",
            TreatMissingData="notBreaching",
        )
        self._cleanup.callback(self.metrics.delete_alarms, AlarmNames=[self.name])

    def emit(self, messages):
        """Emit plain-text messages; ERROR matches the error-count filter."""
        if not messages:
            return
        now = int(time.time() * 1000)
        result = self.logs.put_log_events(
            logGroupName=self.name,
            logStreamName="application",
            logEvents=[{"timestamp": now, "message": message} for message in messages],
        )
        if result.get("rejectedLogEventsInfo"):
            raise RuntimeError("CloudWatch Logs rejected one or more events")

    def records(self):
        """Read delivered gzip envelopes, allowing Floci's newline separators."""
        records = []
        pages = self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.name)
        for page in pages:
            for item in page.get("Contents", []):
                response = self.s3.get_object(Bucket=self.name, Key=item["Key"])
                with response["Body"] as body:
                    remaining = body.read()
                while remaining:
                    decoder = zlib.decompressobj(wbits=31)
                    payload = decoder.decompress(remaining)
                    if not decoder.eof:
                        raise ValueError("Incomplete gzip envelope in S3")
                    records.append(json.loads(payload))
                    remaining = decoder.unused_data.lstrip(b"\n")
        return records

    def wait_for_records(self, timeout=90):
        deadline = time.monotonic() + timeout
        while True:
            records = self.records()
            if records:
                return records
            if time.monotonic() >= deadline:
                raise TimeoutError("No subscription log records arrived in S3")
            time.sleep(1)

    def error_count(self):
        now = datetime.now(UTC)
        response = self.metrics.get_metric_statistics(
            Namespace=self.namespace,
            MetricName="Errors",
            StartTime=now - timedelta(minutes=5),
            EndTime=now + timedelta(minutes=1),
            Period=60,
            Statistics=["Sum"],
        )
        return sum(point["Sum"] for point in response["Datapoints"])

    def alarm(self):
        return self.metrics.describe_alarms(AlarmNames=[self.name])["MetricAlarms"][0]

    def _delete_bucket(self):
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.name):
            for item in page.get("Contents", []):
                self.s3.delete_object(Bucket=self.name, Key=item["Key"])
        self.s3.delete_bucket(Bucket=self.name)

    def __exit__(self, *exc):
        return self._cleanup.__exit__(*exc)
