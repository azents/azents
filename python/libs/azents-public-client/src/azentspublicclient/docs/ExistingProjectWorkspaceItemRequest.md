# ExistingProjectWorkspaceItemRequest

Existing Project workspace item for a new AgentSession.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Workspace item type | 
**path** | **str** | Existing Project path | 

## Example

```python
from azentspublicclient.models.existing_project_workspace_item_request import ExistingProjectWorkspaceItemRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ExistingProjectWorkspaceItemRequest from a JSON string
existing_project_workspace_item_request_instance = ExistingProjectWorkspaceItemRequest.from_json(json)
# print the JSON string representation of the object
print(ExistingProjectWorkspaceItemRequest.to_json())

# convert the object into a dict
existing_project_workspace_item_request_dict = existing_project_workspace_item_request_instance.to_dict()
# create an instance of ExistingProjectWorkspaceItemRequest from a dict
existing_project_workspace_item_request_from_dict = ExistingProjectWorkspaceItemRequest.from_dict(existing_project_workspace_item_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


