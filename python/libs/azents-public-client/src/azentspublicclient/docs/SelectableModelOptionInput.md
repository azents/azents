# SelectableModelOptionInput

Selectable model option input keyed by label.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**label** | **str** | Selectable model label |
**model_selection** | [**AgentModelSelectionInput**](AgentModelSelectionInput.md) | Selectable model selection input |

## Example

```python
from azentspublicclient.models.selectable_model_option_input import SelectableModelOptionInput

# TODO update the JSON string below
json = "{}"
# create an instance of SelectableModelOptionInput from a JSON string
selectable_model_option_input_instance = SelectableModelOptionInput.from_json(json)
# print the JSON string representation of the object
print(SelectableModelOptionInput.to_json())

# convert the object into a dict
selectable_model_option_input_dict = selectable_model_option_input_instance.to_dict()
# create an instance of SelectableModelOptionInput from a dict
selectable_model_option_input_from_dict = SelectableModelOptionInput.from_dict(selectable_model_option_input_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
