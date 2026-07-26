# RuntimeExecutionStorageModule

Nested-engine storage mode and capacity ceiling.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**module_id** | **str** |  | 
**version** | **int** |  | 
**mode** | [**RuntimeExecutionStorageMode**](RuntimeExecutionStorageMode.md) |  | 
**capacity_bytes** | **int** |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_storage_module import RuntimeExecutionStorageModule

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionStorageModule from a JSON string
runtime_execution_storage_module_instance = RuntimeExecutionStorageModule.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionStorageModule.to_json())

# convert the object into a dict
runtime_execution_storage_module_dict = runtime_execution_storage_module_instance.to_dict()
# create an instance of RuntimeExecutionStorageModule from a dict
runtime_execution_storage_module_from_dict = RuntimeExecutionStorageModule.from_dict(runtime_execution_storage_module_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


