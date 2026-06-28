# AgentWorkspaceFileResponse

Agent Workspace file preview response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Response type |
**path** | **str** | File path |
**media_type** | **str** | MIME type |
**size** | **int** | File size |
**text** | **str** |  | [optional]
**truncated** | **bool** | Whether preview was truncated |

## Example

```python
from azentspublicclient.models.agent_workspace_file_response import AgentWorkspaceFileResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceFileResponse from a JSON string
agent_workspace_file_response_instance = AgentWorkspaceFileResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceFileResponse.to_json())

# convert the object into a dict
agent_workspace_file_response_dict = agent_workspace_file_response_instance.to_dict()
# create an instance of AgentWorkspaceFileResponse from a dict
agent_workspace_file_response_from_dict = AgentWorkspaceFileResponse.from_dict(agent_workspace_file_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


