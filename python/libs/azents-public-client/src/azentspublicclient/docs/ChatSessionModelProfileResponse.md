# ChatSessionModelProfileResponse

REST Session model-profile replacement response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session_id** | **str** | AgentSession ID | 
**model_target_label** | **str** | Agent-owned selectable model target label | 
**reasoning_effort** | [**ModelReasoningEffort**](ModelReasoningEffort.md) |  | 

## Example

```python
from azentspublicclient.models.chat_session_model_profile_response import ChatSessionModelProfileResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatSessionModelProfileResponse from a JSON string
chat_session_model_profile_response_instance = ChatSessionModelProfileResponse.from_json(json)
# print the JSON string representation of the object
print(ChatSessionModelProfileResponse.to_json())

# convert the object into a dict
chat_session_model_profile_response_dict = chat_session_model_profile_response_instance.to_dict()
# create an instance of ChatSessionModelProfileResponse from a dict
chat_session_model_profile_response_from_dict = ChatSessionModelProfileResponse.from_dict(chat_session_model_profile_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


