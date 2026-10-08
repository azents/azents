# GitHubUserInstallation

One bounded owner observation with independent repository readiness.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**installation_id** | **int** |  | 
**app_id** | **int** |  | 
**account_login** | **str** |  | 
**account_type** | **str** |  | 
**account_avatar_url** | **str** |  | 
**app_permissions** | **Dict[str, str]** |  | 
**repositories** | [**List[GitHubUserRepository]**](GitHubUserRepository.md) |  | 
**repositories_complete** | **bool** |  | 
**failure_reason** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_installation import GitHubUserInstallation

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserInstallation from a JSON string
git_hub_user_installation_instance = GitHubUserInstallation.from_json(json)
# print the JSON string representation of the object
print(GitHubUserInstallation.to_json())

# convert the object into a dict
git_hub_user_installation_dict = git_hub_user_installation_instance.to_dict()
# create an instance of GitHubUserInstallation from a dict
git_hub_user_installation_from_dict = GitHubUserInstallation.from_dict(git_hub_user_installation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


