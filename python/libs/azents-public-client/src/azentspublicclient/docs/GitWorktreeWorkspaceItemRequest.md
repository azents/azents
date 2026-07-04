# GitWorktreeWorkspaceItemRequest

Git worktree workspace item for a new AgentSession.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Workspace item type |
**source_project_path** | **str** | Source Project path |
**starting_ref** | **str** | Starting local Git branch ref |

## Example

```python
from azentspublicclient.models.git_worktree_workspace_item_request import GitWorktreeWorkspaceItemRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GitWorktreeWorkspaceItemRequest from a JSON string
git_worktree_workspace_item_request_instance = GitWorktreeWorkspaceItemRequest.from_json(json)
# print the JSON string representation of the object
print(GitWorktreeWorkspaceItemRequest.to_json())

# convert the object into a dict
git_worktree_workspace_item_request_dict = git_worktree_workspace_item_request_instance.to_dict()
# create an instance of GitWorktreeWorkspaceItemRequest from a dict
git_worktree_workspace_item_request_from_dict = GitWorktreeWorkspaceItemRequest.from_dict(git_worktree_workspace_item_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
