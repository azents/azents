# SelectableModelOption

Stored selectable semantic label with ordered physical candidates.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**label** | **str** | Selectable model label | 
**candidates** | [**List[SelectableModelCandidate]**](SelectableModelCandidate.md) | Ordered physical model candidates; first is Primary | 
**subagent_enabled** | **bool** | Available as an explicit subagent model target | 
**subagent_guidance** | **str** |  | 

## Example

```python
from azentspublicclient.models.selectable_model_option import SelectableModelOption

# TODO update the JSON string below
json = "{}"
# create an instance of SelectableModelOption from a JSON string
selectable_model_option_instance = SelectableModelOption.from_json(json)
# print the JSON string representation of the object
print(SelectableModelOption.to_json())

# convert the object into a dict
selectable_model_option_dict = selectable_model_option_instance.to_dict()
# create an instance of SelectableModelOption from a dict
selectable_model_option_from_dict = SelectableModelOption.from_dict(selectable_model_option_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


