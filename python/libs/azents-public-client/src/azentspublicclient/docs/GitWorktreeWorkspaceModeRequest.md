# GitWorktreeWorkspaceModeRequest

Git worktree mode for a new AgentSession.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Workspace mode type |
**source_project_path** | **str** | Source Project path |
**starting_ref** | **str** | Starting Git ref |

## Example

```python
from azentspublicclient.models.git_worktree_workspace_mode_request import GitWorktreeWorkspaceModeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GitWorktreeWorkspaceModeRequest from a JSON string
git_worktree_workspace_mode_request_instance = GitWorktreeWorkspaceModeRequest.from_json(json)
# print the JSON string representation of the object
print(GitWorktreeWorkspaceModeRequest.to_json())

# convert the object into a dict
git_worktree_workspace_mode_request_dict = git_worktree_workspace_mode_request_instance.to_dict()
# create an instance of GitWorktreeWorkspaceModeRequest from a dict
git_worktree_workspace_mode_request_from_dict = GitWorktreeWorkspaceModeRequest.from_dict(git_worktree_workspace_mode_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
