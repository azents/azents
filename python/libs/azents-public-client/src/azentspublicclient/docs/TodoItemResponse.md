# TodoItemResponse

Chat live todo item response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**content** | **str** | Todo text | 
**status** | **str** | Todo status | 

## Example

```python
from azentspublicclient.models.todo_item_response import TodoItemResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TodoItemResponse from a JSON string
todo_item_response_instance = TodoItemResponse.from_json(json)
# print the JSON string representation of the object
print(TodoItemResponse.to_json())

# convert the object into a dict
todo_item_response_dict = todo_item_response_instance.to_dict()
# create an instance of TodoItemResponse from a dict
todo_item_response_from_dict = TodoItemResponse.from_dict(todo_item_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


