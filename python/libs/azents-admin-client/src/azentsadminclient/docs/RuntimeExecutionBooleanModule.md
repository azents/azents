# RuntimeExecutionBooleanModule

One versioned boolean execution capability module.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**module_id** | **str** |  | 
**version** | **int** |  | 
**enabled** | **bool** |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_boolean_module import RuntimeExecutionBooleanModule

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionBooleanModule from a JSON string
runtime_execution_boolean_module_instance = RuntimeExecutionBooleanModule.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionBooleanModule.to_json())

# convert the object into a dict
runtime_execution_boolean_module_dict = runtime_execution_boolean_module_instance.to_dict()
# create an instance of RuntimeExecutionBooleanModule from a dict
runtime_execution_boolean_module_from_dict = RuntimeExecutionBooleanModule.from_dict(runtime_execution_boolean_module_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


