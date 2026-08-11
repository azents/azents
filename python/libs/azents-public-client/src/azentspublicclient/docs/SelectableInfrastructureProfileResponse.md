# SelectableInfrastructureProfileResponse

One Provider/Profile option currently selectable by the Workspace.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**provider_id** | **str** |  | 
**provider_display_name** | **str** |  | 
**provider_kind** | **str** |  | 
**profile_kind** | **str** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**spec** | [**RuntimeInfrastructureProfileSpec**](RuntimeInfrastructureProfileSpec.md) |  | 
**required_capabilities** | **List[str]** |  | 
**version** | **int** |  | 
**digest** | **str** |  | 
**capability_revision_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.selectable_infrastructure_profile_response import SelectableInfrastructureProfileResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SelectableInfrastructureProfileResponse from a JSON string
selectable_infrastructure_profile_response_instance = SelectableInfrastructureProfileResponse.from_json(json)
# print the JSON string representation of the object
print(SelectableInfrastructureProfileResponse.to_json())

# convert the object into a dict
selectable_infrastructure_profile_response_dict = selectable_infrastructure_profile_response_instance.to_dict()
# create an instance of SelectableInfrastructureProfileResponse from a dict
selectable_infrastructure_profile_response_from_dict = SelectableInfrastructureProfileResponse.from_dict(selectable_infrastructure_profile_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


