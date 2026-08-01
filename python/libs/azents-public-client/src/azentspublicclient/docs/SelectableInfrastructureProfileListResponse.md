# SelectableInfrastructureProfileListResponse

Workspace-selectable infrastructure Profile list.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[SelectableInfrastructureProfileResponse]**](SelectableInfrastructureProfileResponse.md) |  | 

## Example

```python
from azentspublicclient.models.selectable_infrastructure_profile_list_response import SelectableInfrastructureProfileListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SelectableInfrastructureProfileListResponse from a JSON string
selectable_infrastructure_profile_list_response_instance = SelectableInfrastructureProfileListResponse.from_json(json)
# print the JSON string representation of the object
print(SelectableInfrastructureProfileListResponse.to_json())

# convert the object into a dict
selectable_infrastructure_profile_list_response_dict = selectable_infrastructure_profile_list_response_instance.to_dict()
# create an instance of SelectableInfrastructureProfileListResponse from a dict
selectable_infrastructure_profile_list_response_from_dict = SelectableInfrastructureProfileListResponse.from_dict(selectable_infrastructure_profile_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


