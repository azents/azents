# CreateGitWorktreeAction

Create an Azents-owned Git worktree and register it as a session Project.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'create_git_worktree']
**source_project_path** | **str** | Existing source Project path under the Agent Workspace | 
**starting_ref** | **str** | Starting Git ref for the new worktree branch | 

## Example

```python
from azentspublicclient.models.create_git_worktree_action import CreateGitWorktreeAction

# TODO update the JSON string below
json = "{}"
# create an instance of CreateGitWorktreeAction from a JSON string
create_git_worktree_action_instance = CreateGitWorktreeAction.from_json(json)
# print the JSON string representation of the object
print(CreateGitWorktreeAction.to_json())

# convert the object into a dict
create_git_worktree_action_dict = create_git_worktree_action_instance.to_dict()
# create an instance of CreateGitWorktreeAction from a dict
create_git_worktree_action_from_dict = CreateGitWorktreeAction.from_dict(create_git_worktree_action_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


