# WorkspaceUserResponse

WorkspaceUser response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | WorkspaceUser ID (UUID7 hex) |
**workspace_id** | **str** | Owning Workspace ID |
**user_id** | **str** | User ID |
**name** | **str** | Workspace display name |
**locale** | **str** | Workspace locale (BCP 47) |
**role** | [**WorkspaceUserRole**](WorkspaceUserRole.md) | Role (owner, manager, member) |
**created_at** | **datetime** | Created time |
**updated_at** | **datetime** | Updated time |

## Example

```python
from azentsadminclient.models.workspace_user_response import WorkspaceUserResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUserResponse from a JSON string
workspace_user_response_instance = WorkspaceUserResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUserResponse.to_json())

# convert the object into a dict
workspace_user_response_dict = workspace_user_response_instance.to_dict()
# create an instance of WorkspaceUserResponse from a dict
workspace_user_response_from_dict = WorkspaceUserResponse.from_dict(workspace_user_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
