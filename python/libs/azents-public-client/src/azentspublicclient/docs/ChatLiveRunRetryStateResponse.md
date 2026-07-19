# ChatLiveRunRetryStateResponse

Current live failed-run retry state response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**error_kind** | **str** | Provider or runtime presentation kind | 
**status** | **str** | Current retry status | 
**last_error_message** | **str** | Latest user-safe error message | 
**failed_attempt_count** | **int** | Failed attempt count | 
**max_retries** | **int** | Maximum retry count | 
**backoff_seconds** | **int** | Current backoff duration in seconds | 
**next_retry_at** | **str** | Absolute next retry timestamp | 
**attempts** | [**List[ChatLiveRunRetryAttemptResponse]**](ChatLiveRunRetryAttemptResponse.md) | User-safe retry attempt history | 

## Example

```python
from azentspublicclient.models.chat_live_run_retry_state_response import ChatLiveRunRetryStateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatLiveRunRetryStateResponse from a JSON string
chat_live_run_retry_state_response_instance = ChatLiveRunRetryStateResponse.from_json(json)
# print the JSON string representation of the object
print(ChatLiveRunRetryStateResponse.to_json())

# convert the object into a dict
chat_live_run_retry_state_response_dict = chat_live_run_retry_state_response_instance.to_dict()
# create an instance of ChatLiveRunRetryStateResponse from a dict
chat_live_run_retry_state_response_from_dict = ChatLiveRunRetryStateResponse.from_dict(chat_live_run_retry_state_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


