# ChatLiveRunRetryAttemptResponse

User-safe failed-run retry attempt summary response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**attempt_number** | **int** | Failed attempt number |
**user_message** | **str** | User-safe failed attempt message |
**error_type** | **str** | Exception class or failure type |
**source** | **str** | Failure source boundary |
**failed_at** | **str** | Failure timestamp |
**backoff_seconds** | **int** | Backoff duration after this attempt |
**next_retry_at** | **str** | Retry timestamp after this attempt |
**retryability** | **str** | Retryability classification |
**failure_code** | **str** |  | [optional]
**truncated** | **bool** | Whether user_message was truncated |

## Example

```python
from azentspublicclient.models.chat_live_run_retry_attempt_response import ChatLiveRunRetryAttemptResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatLiveRunRetryAttemptResponse from a JSON string
chat_live_run_retry_attempt_response_instance = ChatLiveRunRetryAttemptResponse.from_json(json)
# print the JSON string representation of the object
print(ChatLiveRunRetryAttemptResponse.to_json())

# convert the object into a dict
chat_live_run_retry_attempt_response_dict = chat_live_run_retry_attempt_response_instance.to_dict()
# create an instance of ChatLiveRunRetryAttemptResponse from a dict
chat_live_run_retry_attempt_response_from_dict = ChatLiveRunRetryAttemptResponse.from_dict(chat_live_run_retry_attempt_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
