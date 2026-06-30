# InputActionListResponse

Composer action list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[InputActionDefinitionResponse]**](InputActionDefinitionResponse.md) | Available composer action definitions | 

## Example

```python
from azentspublicclient.models.input_action_list_response import InputActionListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of InputActionListResponse from a JSON string
input_action_list_response_instance = InputActionListResponse.from_json(json)
# print the JSON string representation of the object
print(InputActionListResponse.to_json())

# convert the object into a dict
input_action_list_response_dict = input_action_list_response_instance.to_dict()
# create an instance of InputActionListResponse from a dict
input_action_list_response_from_dict = InputActionListResponse.from_dict(input_action_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


