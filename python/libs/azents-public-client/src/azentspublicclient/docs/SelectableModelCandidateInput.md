# SelectableModelCandidateInput

Physical model candidate input inside one selectable label.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**model_selection** | [**AgentModelSelectionInput**](AgentModelSelectionInput.md) | Physical model selection input | 
**settings** | [**SelectableModelSettingsInput**](SelectableModelSettingsInput.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.selectable_model_candidate_input import SelectableModelCandidateInput

# TODO update the JSON string below
json = "{}"
# create an instance of SelectableModelCandidateInput from a JSON string
selectable_model_candidate_input_instance = SelectableModelCandidateInput.from_json(json)
# print the JSON string representation of the object
print(SelectableModelCandidateInput.to_json())

# convert the object into a dict
selectable_model_candidate_input_dict = selectable_model_candidate_input_instance.to_dict()
# create an instance of SelectableModelCandidateInput from a dict
selectable_model_candidate_input_from_dict = SelectableModelCandidateInput.from_dict(selectable_model_candidate_input_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


