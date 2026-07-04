# SessionGitWorktreeAttachRequest

Existing-session Git worktree attach request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**source_project_path** | **str** | Source Project path |
**starting_ref** | **str** | Starting Git ref |

## Example

```python
from azentspublicclient.models.session_git_worktree_attach_request import SessionGitWorktreeAttachRequest

# TODO update the JSON string below
json = "{}"
# create an instance of SessionGitWorktreeAttachRequest from a JSON string
session_git_worktree_attach_request_instance = SessionGitWorktreeAttachRequest.from_json(json)
# print the JSON string representation of the object
print(SessionGitWorktreeAttachRequest.to_json())

# convert the object into a dict
session_git_worktree_attach_request_dict = session_git_worktree_attach_request_instance.to_dict()
# create an instance of SessionGitWorktreeAttachRequest from a dict
session_git_worktree_attach_request_from_dict = SessionGitWorktreeAttachRequest.from_dict(session_git_worktree_attach_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
