# AgentRemoveGitWorktreeAction

Remove an admission-pinned managed worktree while preserving its branch.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'agent_remove_git_worktree']
**bridge_identity** | **str** |  | 
**originating_run_id** | **str** |  | 
**client_tool_call_id** | **str** |  | 
**session_agent_context_id** | **str** |  | 
**originating_agent_session_id** | **str** |  | 
**worktree_project_id** | **str** |  | 
**worktree_allocation_id** | **str** |  | 
**worktree_path** | **str** |  | 
**force** | **bool** |  | 

## Example

```python
from azentspublicclient.models.agent_remove_git_worktree_action import AgentRemoveGitWorktreeAction

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRemoveGitWorktreeAction from a JSON string
agent_remove_git_worktree_action_instance = AgentRemoveGitWorktreeAction.from_json(json)
# print the JSON string representation of the object
print(AgentRemoveGitWorktreeAction.to_json())

# convert the object into a dict
agent_remove_git_worktree_action_dict = agent_remove_git_worktree_action_instance.to_dict()
# create an instance of AgentRemoveGitWorktreeAction from a dict
agent_remove_git_worktree_action_from_dict = AgentRemoveGitWorktreeAction.from_dict(agent_remove_git_worktree_action_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


