# ChatSessionCreateMessageWriteRequest

REST first message write request for a draft AgentSession.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**client_request_id** | **str** | Client-generated idempotency key | 
**message** | **str** | Message content | 
**inference_profile** | [**RequestedInferenceProfile**](RequestedInferenceProfile.md) | Requested inference profile for the first model run | 
**existing_project_paths** | **List[str]** | Existing Project paths to register on the created session | 
**setup_actions** | [**List[CreateGitWorktreeAction]**](CreateGitWorktreeAction.md) | Ordered setup actions to enqueue before the first message | 
**attachments** | **List[str]** |  | [optional] 

## Example

```python
from azentspublicclient.models.chat_session_create_message_write_request import ChatSessionCreateMessageWriteRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ChatSessionCreateMessageWriteRequest from a JSON string
chat_session_create_message_write_request_instance = ChatSessionCreateMessageWriteRequest.from_json(json)
# print the JSON string representation of the object
print(ChatSessionCreateMessageWriteRequest.to_json())

# convert the object into a dict
chat_session_create_message_write_request_dict = chat_session_create_message_write_request_instance.to_dict()
# create an instance of ChatSessionCreateMessageWriteRequest from a dict
chat_session_create_message_write_request_from_dict = ChatSessionCreateMessageWriteRequest.from_dict(chat_session_create_message_write_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


