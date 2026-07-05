# ExistingProjectWorkspaceItemResponse

Existing Project default workspace item response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Workspace item type | [optional] [default to 'existing_project']
**path** | **str** | Existing Project path | 

## Example

```python
from azentspublicclient.models.existing_project_workspace_item_response import ExistingProjectWorkspaceItemResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ExistingProjectWorkspaceItemResponse from a JSON string
existing_project_workspace_item_response_instance = ExistingProjectWorkspaceItemResponse.from_json(json)
# print the JSON string representation of the object
print(ExistingProjectWorkspaceItemResponse.to_json())

# convert the object into a dict
existing_project_workspace_item_response_dict = existing_project_workspace_item_response_instance.to_dict()
# create an instance of ExistingProjectWorkspaceItemResponse from a dict
existing_project_workspace_item_response_from_dict = ExistingProjectWorkspaceItemResponse.from_dict(existing_project_workspace_item_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


