# TodoStateResponse

Chat live todo state response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[TodoItemResponse]**](TodoItemResponse.md) | Todo item list |

## Example

```python
from azentspublicclient.models.todo_state_response import TodoStateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TodoStateResponse from a JSON string
todo_state_response_instance = TodoStateResponse.from_json(json)
# print the JSON string representation of the object
print(TodoStateResponse.to_json())

# convert the object into a dict
todo_state_response_dict = todo_state_response_instance.to_dict()
# create an instance of TodoStateResponse from a dict
todo_state_response_from_dict = TodoStateResponse.from_dict(todo_state_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


