# RuntimeExecutionResourceRestriction

Optional lower-layer resource ceilings.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**cpu_request_millicores** | **int** |  | 
**cpu_limit_millicores** | **int** |  | 
**memory_request_bytes** | **int** |  | 
**memory_limit_bytes** | **int** |  | 
**pids** | **int** |  | 
**container_count** | **int** |  | 
**ephemeral_storage_bytes** | **int** |  | 
**persistent_storage_bytes** | **int** |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_resource_restriction import RuntimeExecutionResourceRestriction

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionResourceRestriction from a JSON string
runtime_execution_resource_restriction_instance = RuntimeExecutionResourceRestriction.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionResourceRestriction.to_json())

# convert the object into a dict
runtime_execution_resource_restriction_dict = runtime_execution_resource_restriction_instance.to_dict()
# create an instance of RuntimeExecutionResourceRestriction from a dict
runtime_execution_resource_restriction_from_dict = RuntimeExecutionResourceRestriction.from_dict(runtime_execution_resource_restriction_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


