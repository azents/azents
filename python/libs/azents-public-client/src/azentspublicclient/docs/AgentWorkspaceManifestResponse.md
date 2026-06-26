# AgentWorkspaceManifestResponse

Agent Workspace manifest response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**root** | **str** | Agent Workspace root | 
**cwd** | **str** | Initial working directory | 
**entries** | [**List[AgentWorkspaceEntryResponse]**](AgentWorkspaceEntryResponse.md) | Root entry list | 
**git** | **Dict[str, object]** |  | [optional] 

## Example

```python
from azentspublicclient.models.agent_workspace_manifest_response import AgentWorkspaceManifestResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceManifestResponse from a JSON string
agent_workspace_manifest_response_instance = AgentWorkspaceManifestResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceManifestResponse.to_json())

# convert the object into a dict
agent_workspace_manifest_response_dict = agent_workspace_manifest_response_instance.to_dict()
# create an instance of AgentWorkspaceManifestResponse from a dict
agent_workspace_manifest_response_from_dict = AgentWorkspaceManifestResponse.from_dict(agent_workspace_manifest_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


