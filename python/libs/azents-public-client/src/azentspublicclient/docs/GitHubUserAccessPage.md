# GitHubUserAccessPage

Bounded traversal result with an explicit continuation cursor.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**installations** | [**List[GitHubUserInstallation]**](GitHubUserInstallation.md) |  | 
**next_cursor** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_access_page import GitHubUserAccessPage

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserAccessPage from a JSON string
git_hub_user_access_page_instance = GitHubUserAccessPage.from_json(json)
# print the JSON string representation of the object
print(GitHubUserAccessPage.to_json())

# convert the object into a dict
git_hub_user_access_page_dict = git_hub_user_access_page_instance.to_dict()
# create an instance of GitHubUserAccessPage from a dict
git_hub_user_access_page_from_dict = GitHubUserAccessPage.from_dict(git_hub_user_access_page_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


