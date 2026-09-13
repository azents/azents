# SelectableModelOptionResponse

Public selectable semantic label with ordered candidates.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**label** | **str** |  | 
**candidates** | [**List[SelectableModelCandidateResponse]**](SelectableModelCandidateResponse.md) |  | 
**subagent_enabled** | **bool** |  | 
**subagent_guidance** | **str** |  | 
**execution_option_definitions** | [**List[ModelExecutionOptionDefinition]**](ModelExecutionOptionDefinition.md) |  | 

## Example

```python
from azentspublicclient.models.selectable_model_option_response import SelectableModelOptionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SelectableModelOptionResponse from a JSON string
selectable_model_option_response_instance = SelectableModelOptionResponse.from_json(json)
# print the JSON string representation of the object
print(SelectableModelOptionResponse.to_json())

# convert the object into a dict
selectable_model_option_response_dict = selectable_model_option_response_instance.to_dict()
# create an instance of SelectableModelOptionResponse from a dict
selectable_model_option_response_from_dict = SelectableModelOptionResponse.from_dict(selectable_model_option_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


