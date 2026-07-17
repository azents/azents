# SelectableModelSettingsInput

Optional user settings submitted for one selectable model option.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**context_window_tokens** | **int** |  | [optional] 
**max_output_tokens** | **int** |  | [optional] 
**builtin_tools** | [**List[BuiltinToolConfig]**](BuiltinToolConfig.md) |  | [optional] 
**subagent_enabled** | **bool** | Available as an explicit subagent model target | [optional] [default to True]
**subagent_guidance** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.selectable_model_settings_input import SelectableModelSettingsInput

# TODO update the JSON string below
json = "{}"
# create an instance of SelectableModelSettingsInput from a JSON string
selectable_model_settings_input_instance = SelectableModelSettingsInput.from_json(json)
# print the JSON string representation of the object
print(SelectableModelSettingsInput.to_json())

# convert the object into a dict
selectable_model_settings_input_dict = selectable_model_settings_input_instance.to_dict()
# create an instance of SelectableModelSettingsInput from a dict
selectable_model_settings_input_from_dict = SelectableModelSettingsInput.from_dict(selectable_model_settings_input_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


