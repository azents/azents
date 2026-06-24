# ChatEditMessageWriteRequest

REST user message edit request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | Agent ID |
**client_request_id** | **str** | Client-generated idempotency key |
**message_id** | **str** | Existing user_message event ID to edit |
**message** | **str** | Edited message content |
**attachments** | **List[str]** |  | [optional]

## Example

```python
from azentspublicclient.models.chat_edit_message_write_request import ChatEditMessageWriteRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ChatEditMessageWriteRequest from a JSON string
chat_edit_message_write_request_instance = ChatEditMessageWriteRequest.from_json(json)
# print the JSON string representation of the object
print(ChatEditMessageWriteRequest.to_json())

# convert the object into a dict
chat_edit_message_write_request_dict = chat_edit_message_write_request_instance.to_dict()
# create an instance of ChatEditMessageWriteRequest from a dict
chat_edit_message_write_request_from_dict = ChatEditMessageWriteRequest.from_dict(chat_edit_message_write_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
