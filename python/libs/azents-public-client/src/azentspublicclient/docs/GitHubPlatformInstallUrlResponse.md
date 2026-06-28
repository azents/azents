# GitHubPlatformInstallUrlResponse

GitHub Platform App installation URL response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**install_url** | **str** | GitHub App installation page URL |

## Example

```python
from azentspublicclient.models.git_hub_platform_install_url_response import GitHubPlatformInstallUrlResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubPlatformInstallUrlResponse from a JSON string
git_hub_platform_install_url_response_instance = GitHubPlatformInstallUrlResponse.from_json(json)
# print the JSON string representation of the object
print(GitHubPlatformInstallUrlResponse.to_json())

# convert the object into a dict
git_hub_platform_install_url_response_dict = git_hub_platform_install_url_response_instance.to_dict()
# create an instance of GitHubPlatformInstallUrlResponse from a dict
git_hub_platform_install_url_response_from_dict = GitHubPlatformInstallUrlResponse.from_dict(git_hub_platform_install_url_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


