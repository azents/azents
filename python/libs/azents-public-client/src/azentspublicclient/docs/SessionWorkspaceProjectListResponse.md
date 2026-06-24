# SessionWorkspaceProjectListResponse

Agent Workspace Project list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[SessionWorkspaceProjectResponse]**](SessionWorkspaceProjectResponse.md) | Project list |

## Example

```python
from azentspublicclient.models.session_workspace_project_list_response import SessionWorkspaceProjectListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionWorkspaceProjectListResponse from a JSON string
session_workspace_project_list_response_instance = SessionWorkspaceProjectListResponse.from_json(json)
# print the JSON string representation of the object
print(SessionWorkspaceProjectListResponse.to_json())

# convert the object into a dict
session_workspace_project_list_response_dict = session_workspace_project_list_response_instance.to_dict()
# create an instance of SessionWorkspaceProjectListResponse from a dict
session_workspace_project_list_response_from_dict = SessionWorkspaceProjectListResponse.from_dict(session_workspace_project_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
