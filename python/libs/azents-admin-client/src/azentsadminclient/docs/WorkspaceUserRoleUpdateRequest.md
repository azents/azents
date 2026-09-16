# WorkspaceUserRoleUpdateRequest

WorkspaceUser role update request schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**role** | [**WorkspaceUserRole**](WorkspaceUserRole.md) | Role (manager, member) | 

## Example

```python
from azentsadminclient.models.workspace_user_role_update_request import WorkspaceUserRoleUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUserRoleUpdateRequest from a JSON string
workspace_user_role_update_request_instance = WorkspaceUserRoleUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUserRoleUpdateRequest.to_json())

# convert the object into a dict
workspace_user_role_update_request_dict = workspace_user_role_update_request_instance.to_dict()
# create an instance of WorkspaceUserRoleUpdateRequest from a dict
workspace_user_role_update_request_from_dict = WorkspaceUserRoleUpdateRequest.from_dict(workspace_user_role_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


