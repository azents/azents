# ChatInputWriteRequestAction


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'command']
**name** | **str** | Command name |
**skill_path** | **str** | Exact SKILL.md path |

## Example

```python
from azentspublicclient.models.chat_input_write_request_action import ChatInputWriteRequestAction

# TODO update the JSON string below
json = "{}"
# create an instance of ChatInputWriteRequestAction from a JSON string
chat_input_write_request_action_instance = ChatInputWriteRequestAction.from_json(json)
# print the JSON string representation of the object
print(ChatInputWriteRequestAction.to_json())

# convert the object into a dict
chat_input_write_request_action_dict = chat_input_write_request_action_instance.to_dict()
# create an instance of ChatInputWriteRequestAction from a dict
chat_input_write_request_action_from_dict = ChatInputWriteRequestAction.from_dict(chat_input_write_request_action_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


