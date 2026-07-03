# ExistingProjectsWorkspaceModeRequest

Existing Project path mode for a new AgentSession.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Workspace mode type |
**project_paths** | **List[str]** | Exact Project paths to register on the created session |

## Example

```python
from azentspublicclient.models.existing_projects_workspace_mode_request import ExistingProjectsWorkspaceModeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ExistingProjectsWorkspaceModeRequest from a JSON string
existing_projects_workspace_mode_request_instance = ExistingProjectsWorkspaceModeRequest.from_json(json)
# print the JSON string representation of the object
print(ExistingProjectsWorkspaceModeRequest.to_json())

# convert the object into a dict
existing_projects_workspace_mode_request_dict = existing_projects_workspace_mode_request_instance.to_dict()
# create an instance of ExistingProjectsWorkspaceModeRequest from a dict
existing_projects_workspace_mode_request_from_dict = ExistingProjectsWorkspaceModeRequest.from_dict(existing_projects_workspace_mode_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
