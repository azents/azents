# GitWorktreeWorkspaceItemResponse

Git worktree default workspace item response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Workspace item type | [optional] [default to 'git_worktree']
**source_project_path** | **str** | Source Project path | 
**starting_ref** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.git_worktree_workspace_item_response import GitWorktreeWorkspaceItemResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GitWorktreeWorkspaceItemResponse from a JSON string
git_worktree_workspace_item_response_instance = GitWorktreeWorkspaceItemResponse.from_json(json)
# print the JSON string representation of the object
print(GitWorktreeWorkspaceItemResponse.to_json())

# convert the object into a dict
git_worktree_workspace_item_response_dict = git_worktree_workspace_item_response_instance.to_dict()
# create an instance of GitWorktreeWorkspaceItemResponse from a dict
git_worktree_workspace_item_response_from_dict = GitWorktreeWorkspaceItemResponse.from_dict(git_worktree_workspace_item_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


