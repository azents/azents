# GitHubUserRepositoryPermissions

Observed account permissions; absent provider facts remain unknown.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**read** | **bool** |  | 
**write** | **bool** |  | 
**admin** | **bool** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_repository_permissions import GitHubUserRepositoryPermissions

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserRepositoryPermissions from a JSON string
git_hub_user_repository_permissions_instance = GitHubUserRepositoryPermissions.from_json(json)
# print the JSON string representation of the object
print(GitHubUserRepositoryPermissions.to_json())

# convert the object into a dict
git_hub_user_repository_permissions_dict = git_hub_user_repository_permissions_instance.to_dict()
# create an instance of GitHubUserRepositoryPermissions from a dict
git_hub_user_repository_permissions_from_dict = GitHubUserRepositoryPermissions.from_dict(git_hub_user_repository_permissions_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


