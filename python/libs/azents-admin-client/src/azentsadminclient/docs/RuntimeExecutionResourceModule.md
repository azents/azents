# RuntimeExecutionResourceModule

Aggregate Runtime and nested-workload resource ceilings.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**module_id** | **str** |  | 
**version** | **int** |  | 
**cpu_millicores** | **int** |  | 
**memory_bytes** | **int** |  | 
**pids** | **int** |  | 
**container_count** | **int** |  | 
**ephemeral_storage_bytes** | **int** |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_resource_module import RuntimeExecutionResourceModule

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionResourceModule from a JSON string
runtime_execution_resource_module_instance = RuntimeExecutionResourceModule.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionResourceModule.to_json())

# convert the object into a dict
runtime_execution_resource_module_dict = runtime_execution_resource_module_instance.to_dict()
# create an instance of RuntimeExecutionResourceModule from a dict
runtime_execution_resource_module_from_dict = RuntimeExecutionResourceModule.from_dict(runtime_execution_resource_module_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


