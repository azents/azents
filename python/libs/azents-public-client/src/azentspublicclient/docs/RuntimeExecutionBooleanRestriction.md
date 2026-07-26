# RuntimeExecutionBooleanRestriction

Boolean authority can only be explicitly disabled.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**enabled** | **bool** |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_boolean_restriction import RuntimeExecutionBooleanRestriction

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionBooleanRestriction from a JSON string
runtime_execution_boolean_restriction_instance = RuntimeExecutionBooleanRestriction.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionBooleanRestriction.to_json())

# convert the object into a dict
runtime_execution_boolean_restriction_dict = runtime_execution_boolean_restriction_instance.to_dict()
# create an instance of RuntimeExecutionBooleanRestriction from a dict
runtime_execution_boolean_restriction_from_dict = RuntimeExecutionBooleanRestriction.from_dict(runtime_execution_boolean_restriction_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


