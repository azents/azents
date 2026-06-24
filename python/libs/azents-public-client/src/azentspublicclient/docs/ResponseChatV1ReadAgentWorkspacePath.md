# ResponseChatV1ReadAgentWorkspacePath


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Response type |
**path** | **str** | File path |
**entries** | [**List[AgentWorkspaceEntryResponse]**](AgentWorkspaceEntryResponse.md) | Entry list |
**media_type** | **str** | MIME type |
**size** | **int** | File size |
**text** | **str** |  | [optional]
**truncated** | **bool** | Whether preview was truncated |

## Example

```python
from azentspublicclient.models.response_chat_v1_read_agent_workspace_path import ResponseChatV1ReadAgentWorkspacePath

# TODO update the JSON string below
json = "{}"
# create an instance of ResponseChatV1ReadAgentWorkspacePath from a JSON string
response_chat_v1_read_agent_workspace_path_instance = ResponseChatV1ReadAgentWorkspacePath.from_json(json)
# print the JSON string representation of the object
print(ResponseChatV1ReadAgentWorkspacePath.to_json())

# convert the object into a dict
response_chat_v1_read_agent_workspace_path_dict = response_chat_v1_read_agent_workspace_path_instance.to_dict()
# create an instance of ResponseChatV1ReadAgentWorkspacePath from a dict
response_chat_v1_read_agent_workspace_path_from_dict = ResponseChatV1ReadAgentWorkspacePath.from_dict(response_chat_v1_read_agent_workspace_path_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
