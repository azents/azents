# RuntimeExecutionFieldChange

Security direction for one canonical policy field change.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**path** | **str** |  | 
**direction** | [**RuntimeExecutionChangeDirection**](RuntimeExecutionChangeDirection.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_field_change import RuntimeExecutionFieldChange

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionFieldChange from a JSON string
runtime_execution_field_change_instance = RuntimeExecutionFieldChange.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionFieldChange.to_json())

# convert the object into a dict
runtime_execution_field_change_dict = runtime_execution_field_change_instance.to_dict()
# create an instance of RuntimeExecutionFieldChange from a dict
runtime_execution_field_change_from_dict = RuntimeExecutionFieldChange.from_dict(runtime_execution_field_change_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


