# ChatMessageWriteRequest

REST message write request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | Agent ID |
**client_request_id** | **str** | Client-generated idempotency key |
**message** | **str** | Message content |
**attachments** | **List[str]** |  | [optional]

## Example

```python
from azentspublicclient.models.chat_message_write_request import ChatMessageWriteRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ChatMessageWriteRequest from a JSON string
chat_message_write_request_instance = ChatMessageWriteRequest.from_json(json)
# print the JSON string representation of the object
print(ChatMessageWriteRequest.to_json())

# convert the object into a dict
chat_message_write_request_dict = chat_message_write_request_instance.to_dict()
# create an instance of ChatMessageWriteRequest from a dict
chat_message_write_request_from_dict = ChatMessageWriteRequest.from_dict(chat_message_write_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
