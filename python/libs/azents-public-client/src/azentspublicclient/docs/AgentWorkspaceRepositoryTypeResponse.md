# AgentWorkspaceRepositoryTypeResponse

Repository metadata for one explicitly inspected Workspace directory.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**repository_type** | **str** |  | 

## Example

```python
from azentspublicclient.models.agent_workspace_repository_type_response import AgentWorkspaceRepositoryTypeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceRepositoryTypeResponse from a JSON string
agent_workspace_repository_type_response_instance = AgentWorkspaceRepositoryTypeResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceRepositoryTypeResponse.to_json())

# convert the object into a dict
agent_workspace_repository_type_response_dict = agent_workspace_repository_type_response_instance.to_dict()
# create an instance of AgentWorkspaceRepositoryTypeResponse from a dict
agent_workspace_repository_type_response_from_dict = AgentWorkspaceRepositoryTypeResponse.from_dict(agent_workspace_repository_type_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


