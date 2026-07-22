# CreateWorkspaceRequest

Workspace creation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workspace_name** | **str** | Workspace name | 
**workspace_handle** | **str** | Workspace handle | 
**owner_name** | **str** | Owner display name | 

## Example

```python
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of CreateWorkspaceRequest from a JSON string
create_workspace_request_instance = CreateWorkspaceRequest.from_json(json)
# print the JSON string representation of the object
print(CreateWorkspaceRequest.to_json())

# convert the object into a dict
create_workspace_request_dict = create_workspace_request_instance.to_dict()
# create an instance of CreateWorkspaceRequest from a dict
create_workspace_request_from_dict = CreateWorkspaceRequest.from_dict(create_workspace_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


