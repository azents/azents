# SelectableModelCandidateResponse

Public physical model candidate snapshot.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**model_selection** | [**AgentModelSelection**](AgentModelSelection.md) |  | 
**settings** | [**SelectableModelSettings**](SelectableModelSettings.md) |  | 

## Example

```python
from azentspublicclient.models.selectable_model_candidate_response import SelectableModelCandidateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SelectableModelCandidateResponse from a JSON string
selectable_model_candidate_response_instance = SelectableModelCandidateResponse.from_json(json)
# print the JSON string representation of the object
print(SelectableModelCandidateResponse.to_json())

# convert the object into a dict
selectable_model_candidate_response_dict = selectable_model_candidate_response_instance.to_dict()
# create an instance of SelectableModelCandidateResponse from a dict
selectable_model_candidate_response_from_dict = SelectableModelCandidateResponse.from_dict(selectable_model_candidate_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


