# RuntimeExecutionSourceVersions

Current mutable source versions captured by one resolution.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**platform** | **int** |  | 
**profile** | **int** |  | 
**workspace** | **int** |  | 
**agent** | **int** |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_source_versions import RuntimeExecutionSourceVersions

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionSourceVersions from a JSON string
runtime_execution_source_versions_instance = RuntimeExecutionSourceVersions.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionSourceVersions.to_json())

# convert the object into a dict
runtime_execution_source_versions_dict = runtime_execution_source_versions_instance.to_dict()
# create an instance of RuntimeExecutionSourceVersions from a dict
runtime_execution_source_versions_from_dict = RuntimeExecutionSourceVersions.from_dict(runtime_execution_source_versions_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


