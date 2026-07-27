# RuntimeExecutionDockerModule

Complete Docker capability and its private data-volume lifecycle.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**module_id** | **str** |  | 
**version** | **int** |  | 
**enabled** | **bool** |  | 
**storage_mode** | [**RuntimeExecutionStorageMode**](RuntimeExecutionStorageMode.md) |  | 
**storage_capacity_bytes** | **int** |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_docker_module import RuntimeExecutionDockerModule

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionDockerModule from a JSON string
runtime_execution_docker_module_instance = RuntimeExecutionDockerModule.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionDockerModule.to_json())

# convert the object into a dict
runtime_execution_docker_module_dict = runtime_execution_docker_module_instance.to_dict()
# create an instance of RuntimeExecutionDockerModule from a dict
runtime_execution_docker_module_from_dict = RuntimeExecutionDockerModule.from_dict(runtime_execution_docker_module_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


