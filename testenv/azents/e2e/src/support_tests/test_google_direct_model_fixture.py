"""Incremental synthetic-model requests cannot replay issued Google writes."""

from support import image_generation_openai_proxy as proxy


def test_incremental_response_identity_preserves_prior_write_progress() -> None:
    request = proxy._decode_model_request(
        {
            "previous_response_id": "resp_google_direct_send",
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_google_direct_send",
                    "output": '{"id":"sent-fixture"}',
                }
            ],
        }
    )
    completed = proxy._google_direct_completed_stages(
        request,
        ["calendar", "mail", "send", "download"],
    )
    assert completed == {
        "call_google_direct_calendar",
        "call_google_direct_mail",
        "call_google_direct_send",
    }


def test_unrelated_response_identity_does_not_invent_google_progress() -> None:
    request = proxy._decode_model_request(
        {
            "previous_response_id": "resp_unrelated",
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_google_direct_calendar",
                    "output": '{"id":"event-fixture"}',
                }
            ],
        }
    )
    assert proxy._google_direct_completed_stages(request, ["calendar", "mail"]) == {
        "call_google_direct_calendar",
    }
