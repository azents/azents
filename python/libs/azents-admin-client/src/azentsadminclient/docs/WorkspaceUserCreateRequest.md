# WorkspaceUserCreateRequest

WorkspaceUser creation request schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workspace_handle** | **str** | Owning Workspace handle | 
**user_id** | **str** | User ID | 
**name** | **str** | Workspace display name | 
**locale** | **str** | Workspace locale (BCP 47) | [optional] [default to 'ko-KR']
**role** | [**WorkspaceUserRole**](WorkspaceUserRole.md) | Role (owner, manager, member) | 

## Example

```python
from azentsadminclient.models.workspace_user_create_request import WorkspaceUserCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUserCreateRequest from a JSON string
workspace_user_create_request_instance = WorkspaceUserCreateRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUserCreateRequest.to_json())

# convert the object into a dict
workspace_user_create_request_dict = workspace_user_create_request_instance.to_dict()
# create an instance of WorkspaceUserCreateRequest from a dict
workspace_user_create_request_from_dict = WorkspaceUserCreateRequest.from_dict(workspace_user_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


