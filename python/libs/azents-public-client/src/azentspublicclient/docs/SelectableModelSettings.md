# SelectableModelSettings

Stored user settings for one selectable model option.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**context_window_tokens** | **int** |  | 
**max_output_tokens** | **int** |  | 
**builtin_tools** | [**List[BuiltinToolConfig]**](BuiltinToolConfig.md) | Enabled built-in tools | 
**subagent_enabled** | **bool** | Available as an explicit subagent model target | 
**subagent_guidance** | **str** |  | 

## Example

```python
from azentspublicclient.models.selectable_model_settings import SelectableModelSettings

# TODO update the JSON string below
json = "{}"
# create an instance of SelectableModelSettings from a JSON string
selectable_model_settings_instance = SelectableModelSettings.from_json(json)
# print the JSON string representation of the object
print(SelectableModelSettings.to_json())

# convert the object into a dict
selectable_model_settings_dict = selectable_model_settings_instance.to_dict()
# create an instance of SelectableModelSettings from a dict
selectable_model_settings_from_dict = SelectableModelSettings.from_dict(selectable_model_settings_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


