# RuntimeExecutionResourceModule

Kubernetes resources for the Runtime workload and Workspace volume.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**module_id** | **str** |  | 
**version** | **int** |  | 
**cpu_request_millicores** | **int** |  | 
**cpu_limit_millicores** | **int** |  | 
**memory_request_bytes** | **int** |  | 
**memory_limit_bytes** | **int** |  | 
**ephemeral_storage_bytes** | **int** |  | 
**persistent_storage_bytes** | **int** |  | 

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


