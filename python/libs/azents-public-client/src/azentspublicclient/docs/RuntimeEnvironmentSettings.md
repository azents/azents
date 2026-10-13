# RuntimeEnvironmentSettings

Per-Agent management state; secret values never leave through this model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**entries** | [**List[RuntimeEnvironmentEntry]**](RuntimeEnvironmentEntry.md) |  | 
**can_manage** | **bool** |  | 

## Example

```python
from azentspublicclient.models.runtime_environment_settings import RuntimeEnvironmentSettings

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeEnvironmentSettings from a JSON string
runtime_environment_settings_instance = RuntimeEnvironmentSettings.from_json(json)
# print the JSON string representation of the object
print(RuntimeEnvironmentSettings.to_json())

# convert the object into a dict
runtime_environment_settings_dict = runtime_environment_settings_instance.to_dict()
# create an instance of RuntimeEnvironmentSettings from a dict
runtime_environment_settings_from_dict = RuntimeEnvironmentSettings.from_dict(runtime_environment_settings_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


