# ChatSessionModelProfileUpdateRequest

REST Session model-profile replacement request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**client_request_id** | **str** | Client-generated idempotency key | 
**model_target_label** | **str** | Agent-owned selectable model target label | 
**reasoning_effort** | [**ModelReasoningEffort**](ModelReasoningEffort.md) |  | 

## Example

```python
from azentspublicclient.models.chat_session_model_profile_update_request import ChatSessionModelProfileUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ChatSessionModelProfileUpdateRequest from a JSON string
chat_session_model_profile_update_request_instance = ChatSessionModelProfileUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(ChatSessionModelProfileUpdateRequest.to_json())

# convert the object into a dict
chat_session_model_profile_update_request_dict = chat_session_model_profile_update_request_instance.to_dict()
# create an instance of ChatSessionModelProfileUpdateRequest from a dict
chat_session_model_profile_update_request_from_dict = ChatSessionModelProfileUpdateRequest.from_dict(chat_session_model_profile_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


