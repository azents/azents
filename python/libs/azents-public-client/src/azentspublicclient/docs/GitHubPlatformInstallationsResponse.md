# GitHubPlatformInstallationsResponse

GitHub Platform App installation list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**installations** | [**List[GitHubInstallationItem]**](GitHubInstallationItem.md) | Installation list |

## Example

```python
from azentspublicclient.models.git_hub_platform_installations_response import GitHubPlatformInstallationsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubPlatformInstallationsResponse from a JSON string
git_hub_platform_installations_response_instance = GitHubPlatformInstallationsResponse.from_json(json)
# print the JSON string representation of the object
print(GitHubPlatformInstallationsResponse.to_json())

# convert the object into a dict
git_hub_platform_installations_response_dict = git_hub_platform_installations_response_instance.to_dict()
# create an instance of GitHubPlatformInstallationsResponse from a dict
git_hub_platform_installations_response_from_dict = GitHubPlatformInstallationsResponse.from_dict(git_hub_platform_installations_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
