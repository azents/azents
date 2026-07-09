# SubagentSettings

Subagent execution settings.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**max_subagents** | **int** | Maximum active subagents per root session | [optional] [default to 3]
**max_depth** | **int** | Maximum subagent tree depth below the root agent | [optional] [default to 1]

## Example

```python
from azentspublicclient.models.subagent_settings import SubagentSettings

# TODO update the JSON string below
json = "{}"
# create an instance of SubagentSettings from a JSON string
subagent_settings_instance = SubagentSettings.from_json(json)
# print the JSON string representation of the object
print(SubagentSettings.to_json())

# convert the object into a dict
subagent_settings_dict = subagent_settings_instance.to_dict()
# create an instance of SubagentSettings from a dict
subagent_settings_from_dict = SubagentSettings.from_dict(subagent_settings_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
