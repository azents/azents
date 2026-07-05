# CleanupSessionGitWorktreeRequest

Request a cleanup target for an Azents-owned session Git worktree.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**project_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.cleanup_session_git_worktree_request import CleanupSessionGitWorktreeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of CleanupSessionGitWorktreeRequest from a JSON string
cleanup_session_git_worktree_request_instance = CleanupSessionGitWorktreeRequest.from_json(json)
# print the JSON string representation of the object
print(CleanupSessionGitWorktreeRequest.to_json())

# convert the object into a dict
cleanup_session_git_worktree_request_dict = cleanup_session_git_worktree_request_instance.to_dict()
# create an instance of CleanupSessionGitWorktreeRequest from a dict
cleanup_session_git_worktree_request_from_dict = CleanupSessionGitWorktreeRequest.from_dict(cleanup_session_git_worktree_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


