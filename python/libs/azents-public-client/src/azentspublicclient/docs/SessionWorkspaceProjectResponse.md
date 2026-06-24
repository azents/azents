# SessionWorkspaceProjectResponse

Agent Workspace Project response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Project ID |
**path** | **str** | Agent Workspace absolute path |
**created_at** | **datetime** | Created time |
**updated_at** | **datetime** | Updated time |

## Example

```python
from azentspublicclient.models.session_workspace_project_response import SessionWorkspaceProjectResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionWorkspaceProjectResponse from a JSON string
session_workspace_project_response_instance = SessionWorkspaceProjectResponse.from_json(json)
# print the JSON string representation of the object
print(SessionWorkspaceProjectResponse.to_json())

# convert the object into a dict
session_workspace_project_response_dict = session_workspace_project_response_instance.to_dict()
# create an instance of SessionWorkspaceProjectResponse from a dict
session_workspace_project_response_from_dict = SessionWorkspaceProjectResponse.from_dict(session_workspace_project_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
