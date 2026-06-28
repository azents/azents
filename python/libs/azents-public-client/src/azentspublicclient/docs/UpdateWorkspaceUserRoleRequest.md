# UpdateWorkspaceUserRoleRequest

WorkspaceUser role change request schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**role** | [**WorkspaceUserRole**](WorkspaceUserRole.md) | Role to change to (owner, manager, member) |

## Example

```python
from azentspublicclient.models.update_workspace_user_role_request import UpdateWorkspaceUserRoleRequest

# TODO update the JSON string below
json = "{}"
# create an instance of UpdateWorkspaceUserRoleRequest from a JSON string
update_workspace_user_role_request_instance = UpdateWorkspaceUserRoleRequest.from_json(json)
# print the JSON string representation of the object
print(UpdateWorkspaceUserRoleRequest.to_json())

# convert the object into a dict
update_workspace_user_role_request_dict = update_workspace_user_role_request_instance.to_dict()
# create an instance of UpdateWorkspaceUserRoleRequest from a dict
update_workspace_user_role_request_from_dict = UpdateWorkspaceUserRoleRequest.from_dict(update_workspace_user_role_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


