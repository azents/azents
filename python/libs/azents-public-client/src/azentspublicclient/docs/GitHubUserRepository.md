# GitHubUserRepository

Owner-qualified repository observation, not a local execution allowlist.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**repository_id** | **int** |  | 
**owner_login** | **str** |  | 
**name** | **str** |  | 
**full_name** | **str** |  | 
**private** | **bool** |  | 
**permissions** | [**GitHubUserRepositoryPermissions**](GitHubUserRepositoryPermissions.md) |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_repository import GitHubUserRepository

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserRepository from a JSON string
git_hub_user_repository_instance = GitHubUserRepository.from_json(json)
# print the JSON string representation of the object
print(GitHubUserRepository.to_json())

# convert the object into a dict
git_hub_user_repository_dict = git_hub_user_repository_instance.to_dict()
# create an instance of GitHubUserRepository from a dict
git_hub_user_repository_from_dict = GitHubUserRepository.from_dict(git_hub_user_repository_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


