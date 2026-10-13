# StoredRuntimeEnvironmentValue

Retain an existing secret by its exact persisted variable name.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**name** | **str** |  | 

## Example

```python
from azentspublicclient.models.stored_runtime_environment_value import StoredRuntimeEnvironmentValue

# TODO update the JSON string below
json = "{}"
# create an instance of StoredRuntimeEnvironmentValue from a JSON string
stored_runtime_environment_value_instance = StoredRuntimeEnvironmentValue.from_json(json)
# print the JSON string representation of the object
print(StoredRuntimeEnvironmentValue.to_json())

# convert the object into a dict
stored_runtime_environment_value_dict = stored_runtime_environment_value_instance.to_dict()
# create an instance of StoredRuntimeEnvironmentValue from a dict
stored_runtime_environment_value_from_dict = StoredRuntimeEnvironmentValue.from_dict(stored_runtime_environment_value_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


