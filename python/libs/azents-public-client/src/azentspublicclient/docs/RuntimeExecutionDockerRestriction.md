# RuntimeExecutionDockerRestriction

Optional lower-layer Docker authority narrowing.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**enabled** | **bool** |  | 
**storage_mode** | [**RuntimeExecutionStorageMode**](RuntimeExecutionStorageMode.md) |  | 
**storage_capacity_bytes** | **int** |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_docker_restriction import RuntimeExecutionDockerRestriction

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionDockerRestriction from a JSON string
runtime_execution_docker_restriction_instance = RuntimeExecutionDockerRestriction.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionDockerRestriction.to_json())

# convert the object into a dict
runtime_execution_docker_restriction_dict = runtime_execution_docker_restriction_instance.to_dict()
# create an instance of RuntimeExecutionDockerRestriction from a dict
runtime_execution_docker_restriction_from_dict = RuntimeExecutionDockerRestriction.from_dict(runtime_execution_docker_restriction_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


