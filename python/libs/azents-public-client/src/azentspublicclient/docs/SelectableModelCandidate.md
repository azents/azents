# SelectableModelCandidate

Stored physical model candidate inside one selectable label.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**model_selection** | [**AgentModelSelection**](AgentModelSelection.md) | Physical model selection snapshot | 
**settings** | [**SelectableModelSettings**](SelectableModelSettings.md) | Stored model-scoped settings | 

## Example

```python
from azentspublicclient.models.selectable_model_candidate import SelectableModelCandidate

# TODO update the JSON string below
json = "{}"
# create an instance of SelectableModelCandidate from a JSON string
selectable_model_candidate_instance = SelectableModelCandidate.from_json(json)
# print the JSON string representation of the object
print(SelectableModelCandidate.to_json())

# convert the object into a dict
selectable_model_candidate_dict = selectable_model_candidate_instance.to_dict()
# create an instance of SelectableModelCandidate from a dict
selectable_model_candidate_from_dict = SelectableModelCandidate.from_dict(selectable_model_candidate_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


