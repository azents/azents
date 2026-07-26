# RuntimeExecutionStorageRestriction

Optional lower-layer engine-storage narrowing.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mode** | [**RuntimeExecutionStorageMode**](RuntimeExecutionStorageMode.md) |  | 
**capacity_bytes** | **int** |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_storage_restriction import RuntimeExecutionStorageRestriction

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionStorageRestriction from a JSON string
runtime_execution_storage_restriction_instance = RuntimeExecutionStorageRestriction.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionStorageRestriction.to_json())

# convert the object into a dict
runtime_execution_storage_restriction_dict = runtime_execution_storage_restriction_instance.to_dict()
# create an instance of RuntimeExecutionStorageRestriction from a dict
runtime_execution_storage_restriction_from_dict = RuntimeExecutionStorageRestriction.from_dict(runtime_execution_storage_restriction_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


