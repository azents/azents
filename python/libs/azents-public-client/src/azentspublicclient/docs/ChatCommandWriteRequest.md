# ChatCommandWriteRequest

REST slash command request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | Agent ID |
**client_request_id** | **str** | Client-generated idempotency key |
**command** | **str** | Command name, for example compact |

## Example

```python
from azentspublicclient.models.chat_command_write_request import ChatCommandWriteRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ChatCommandWriteRequest from a JSON string
chat_command_write_request_instance = ChatCommandWriteRequest.from_json(json)
# print the JSON string representation of the object
print(ChatCommandWriteRequest.to_json())

# convert the object into a dict
chat_command_write_request_dict = chat_command_write_request_instance.to_dict()
# create an instance of ChatCommandWriteRequest from a dict
chat_command_write_request_from_dict = ChatCommandWriteRequest.from_dict(chat_command_write_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
