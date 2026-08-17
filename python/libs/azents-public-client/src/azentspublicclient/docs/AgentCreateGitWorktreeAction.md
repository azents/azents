# AgentCreateGitWorktreeAction

Create a managed worktree from an admission-pinned Session Project.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'agent_create_git_worktree']
**bridge_identity** | **str** |  | 
**originating_run_id** | **str** |  | 
**client_tool_call_id** | **str** |  | 
**session_agent_context_id** | **str** |  | 
**originating_agent_session_id** | **str** |  | 
**source_project_id** | **str** |  | 
**source_project_path** | **str** |  | 
**starting_ref** | **str** |  | 
**branch_name** | **str** |  | 

## Example

```python
from azentspublicclient.models.agent_create_git_worktree_action import AgentCreateGitWorktreeAction

# TODO update the JSON string below
json = "{}"
# create an instance of AgentCreateGitWorktreeAction from a JSON string
agent_create_git_worktree_action_instance = AgentCreateGitWorktreeAction.from_json(json)
# print the JSON string representation of the object
print(AgentCreateGitWorktreeAction.to_json())

# convert the object into a dict
agent_create_git_worktree_action_dict = agent_create_git_worktree_action_instance.to_dict()
# create an instance of AgentCreateGitWorktreeAction from a dict
agent_create_git_worktree_action_from_dict = AgentCreateGitWorktreeAction.from_dict(agent_create_git_worktree_action_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


