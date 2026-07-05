# ChatFailedRunRetryRequest

REST failed-run retry request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | Agent ID | 
**failed_event_id** | **str** | Terminal failed-run system_error event ID | 
**client_request_id** | **str** | Client-generated idempotency key | 

## Example

```python
from azentspublicclient.models.chat_failed_run_retry_request import ChatFailedRunRetryRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ChatFailedRunRetryRequest from a JSON string
chat_failed_run_retry_request_instance = ChatFailedRunRetryRequest.from_json(json)
# print the JSON string representation of the object
print(ChatFailedRunRetryRequest.to_json())

# convert the object into a dict
chat_failed_run_retry_request_dict = chat_failed_run_retry_request_instance.to_dict()
# create an instance of ChatFailedRunRetryRequest from a dict
chat_failed_run_retry_request_from_dict = ChatFailedRunRetryRequest.from_dict(chat_failed_run_retry_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


