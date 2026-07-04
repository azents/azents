# SessionGitWorktreeAttachResponse

Existing-session Git worktree attach response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**worktree_id** | **str** | Queued SessionGitWorktree ID |
**initialization** | [**SessionInitializationResponse**](SessionInitializationResponse.md) | Updated session initialization projection |

## Example

```python
from azentspublicclient.models.session_git_worktree_attach_response import SessionGitWorktreeAttachResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionGitWorktreeAttachResponse from a JSON string
session_git_worktree_attach_response_instance = SessionGitWorktreeAttachResponse.from_json(json)
# print the JSON string representation of the object
print(SessionGitWorktreeAttachResponse.to_json())

# convert the object into a dict
session_git_worktree_attach_response_dict = session_git_worktree_attach_response_instance.to_dict()
# create an instance of SessionGitWorktreeAttachResponse from a dict
session_git_worktree_attach_response_from_dict = SessionGitWorktreeAttachResponse.from_dict(session_git_worktree_attach_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
