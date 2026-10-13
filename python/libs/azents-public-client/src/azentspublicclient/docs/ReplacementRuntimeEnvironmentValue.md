# ReplacementRuntimeEnvironmentValue

Explicit replacement, including a valid empty environment value.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**value** | **str** |  | 

## Example

```python
from azentspublicclient.models.replacement_runtime_environment_value import ReplacementRuntimeEnvironmentValue

# TODO update the JSON string below
json = "{}"
# create an instance of ReplacementRuntimeEnvironmentValue from a JSON string
replacement_runtime_environment_value_instance = ReplacementRuntimeEnvironmentValue.from_json(json)
# print the JSON string representation of the object
print(ReplacementRuntimeEnvironmentValue.to_json())

# convert the object into a dict
replacement_runtime_environment_value_dict = replacement_runtime_environment_value_instance.to_dict()
# create an instance of ReplacementRuntimeEnvironmentValue from a dict
replacement_runtime_environment_value_from_dict = ReplacementRuntimeEnvironmentValue.from_dict(replacement_runtime_environment_value_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


