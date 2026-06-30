# SessionWorkspaceProjectRegisterRequest

Existing Agent Workspace folder Project registration request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**path** | **str** | Existing directory path under /workspace/agent | 

## Example

```python
from azentspublicclient.models.session_workspace_project_register_request import SessionWorkspaceProjectRegisterRequest

# TODO update the JSON string below
json = "{}"
# create an instance of SessionWorkspaceProjectRegisterRequest from a JSON string
session_workspace_project_register_request_instance = SessionWorkspaceProjectRegisterRequest.from_json(json)
# print the JSON string representation of the object
print(SessionWorkspaceProjectRegisterRequest.to_json())

# convert the object into a dict
session_workspace_project_register_request_dict = session_workspace_project_register_request_instance.to_dict()
# create an instance of SessionWorkspaceProjectRegisterRequest from a dict
session_workspace_project_register_request_from_dict = SessionWorkspaceProjectRegisterRequest.from_dict(session_workspace_project_register_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


