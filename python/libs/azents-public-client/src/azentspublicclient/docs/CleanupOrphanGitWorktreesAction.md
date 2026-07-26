# CleanupOrphanGitWorktreesAction

Remove orphaned Git worktrees from the current Agent Runtime.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'cleanup_orphan_git_worktrees']

## Example

```python
from azentspublicclient.models.cleanup_orphan_git_worktrees_action import CleanupOrphanGitWorktreesAction

# TODO update the JSON string below
json = "{}"
# create an instance of CleanupOrphanGitWorktreesAction from a JSON string
cleanup_orphan_git_worktrees_action_instance = CleanupOrphanGitWorktreesAction.from_json(json)
# print the JSON string representation of the object
print(CleanupOrphanGitWorktreesAction.to_json())

# convert the object into a dict
cleanup_orphan_git_worktrees_action_dict = cleanup_orphan_git_worktrees_action_instance.to_dict()
# create an instance of CleanupOrphanGitWorktreesAction from a dict
cleanup_orphan_git_worktrees_action_from_dict = CleanupOrphanGitWorktreesAction.from_dict(cleanup_orphan_git_worktrees_action_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


