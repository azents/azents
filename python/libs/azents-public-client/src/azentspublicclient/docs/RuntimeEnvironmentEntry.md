# RuntimeEnvironmentEntry

Redacted stored entry metadata.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | 
**has_value** | **bool** |  | 

## Example

```python
from azentspublicclient.models.runtime_environment_entry import RuntimeEnvironmentEntry

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeEnvironmentEntry from a JSON string
runtime_environment_entry_instance = RuntimeEnvironmentEntry.from_json(json)
# print the JSON string representation of the object
print(RuntimeEnvironmentEntry.to_json())

# convert the object into a dict
runtime_environment_entry_dict = runtime_environment_entry_instance.to_dict()
# create an instance of RuntimeEnvironmentEntry from a dict
runtime_environment_entry_from_dict = RuntimeEnvironmentEntry.from_dict(runtime_environment_entry_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


