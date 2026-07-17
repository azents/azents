# ChatStoppedRunRetryRequest

REST stopped-run retry request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | Agent ID | 
**stopped_run_id** | **str** | Recoverable stopped AgentRun ID | 
**client_request_id** | **str** | Client-generated idempotency key | 

## Example

```python
from azentspublicclient.models.chat_stopped_run_retry_request import ChatStoppedRunRetryRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ChatStoppedRunRetryRequest from a JSON string
chat_stopped_run_retry_request_instance = ChatStoppedRunRetryRequest.from_json(json)
# print the JSON string representation of the object
print(ChatStoppedRunRetryRequest.to_json())

# convert the object into a dict
chat_stopped_run_retry_request_dict = chat_stopped_run_retry_request_instance.to_dict()
# create an instance of ChatStoppedRunRetryRequest from a dict
chat_stopped_run_retry_request_from_dict = ChatStoppedRunRetryRequest.from_dict(chat_stopped_run_retry_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


