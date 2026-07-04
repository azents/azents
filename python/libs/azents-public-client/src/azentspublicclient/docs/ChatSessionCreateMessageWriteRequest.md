# ChatSessionCreateMessageWriteRequest

REST first message write request for a draft AgentSession.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**client_request_id** | **str** | Client-generated idempotency key | 
**message** | **str** | Message content | 
**workspace_mode** | [**WorkspaceMode**](WorkspaceMode.md) |  | [optional] 
**project_paths** | **List[str]** |  | [optional] 
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


