"""Validate nominal fixture bytes with the installed public AWS SDK parser."""

import json
from collections.abc import Iterator
from dataclasses import dataclass

import boto3
import pytest
from botocore.eventstream import EventStream
from botocore.parsers import EventStreamJSONParser

from support.provider_core_cloud import (
    CORE_TEXT,
    bedrock_core_response,
    inference_profile_source_payload,
)


@dataclass
class _Body:
    data: bytes
    closed: bool = False

    def stream(self) -> Iterator[bytes]:
        yield self.data

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("structured", [False, True])
def test_bedrock_nominal_envelope_uses_valid_native_tagged_unions(
    structured: bool,
) -> None:
    """Both core text and title output reach real SDK event parsing."""
    request = (
        {"toolConfig": {"tools": [{"toolSpec": {"name": "json_tool_call"}}]}}
        if structured
        else {}
    )
    body = _Body(bedrock_core_response(json.dumps(request).encode()))
    client = boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="synthetic",
        aws_secret_access_key="synthetic",
    )
    operation = client.meta.service_model.operation_model("ConverseStream")
    assert operation.output_shape is not None
    stream = EventStream(
        body,
        operation.output_shape.members["stream"],
        EventStreamJSONParser(),
        "ConverseStream",
    )
    try:
        events = list(stream)
        assert events[-1]["metadata"]["usage"]["totalTokens"] == 5
        delta = next(
            event["contentBlockDelta"]["delta"]
            for event in events
            if "contentBlockDelta" in event
        )
        assert delta == (
            {"toolUse": {"input": CORE_TEXT}} if structured else {"text": CORE_TEXT}
        )
        assert events[-2] == {
            "messageStop": {"stopReason": "tool_use" if structured else "end_turn"}
        }
    finally:
        stream.close()
        client.close()
    assert body.closed


def test_profile_source_fixture_has_explicit_standard_and_priority_prices() -> None:
    """The Admin ingestion payload owns prices, not a model SDK price table."""
    payload = inference_profile_source_payload()
    assert set(payload) == {"gpt-5.5", "gpt-5.5-mini", "gpt-6-astra", "gpt-5.6-sol"}
    assert all(
        metadata["litellm_provider"] == "openai"
        and metadata["mode"] == "chat"
        and metadata["input_cost_per_token"] == 0.000001
        and metadata["output_cost_per_token_priority"] == 0.000004
        for metadata in payload.values()
    )
