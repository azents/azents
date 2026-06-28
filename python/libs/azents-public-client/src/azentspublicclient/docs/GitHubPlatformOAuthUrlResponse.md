# GitHubPlatformOAuthUrlResponse

GitHub Platform App OAuth URL response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**oauth_url** | **str** | GitHub OAuth authorization URL |

## Example

```python
from azentspublicclient.models.git_hub_platform_o_auth_url_response import GitHubPlatformOAuthUrlResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubPlatformOAuthUrlResponse from a JSON string
git_hub_platform_o_auth_url_response_instance = GitHubPlatformOAuthUrlResponse.from_json(json)
# print the JSON string representation of the object
print(GitHubPlatformOAuthUrlResponse.to_json())

# convert the object into a dict
git_hub_platform_o_auth_url_response_dict = git_hub_platform_o_auth_url_response_instance.to_dict()
# create an instance of GitHubPlatformOAuthUrlResponse from a dict
git_hub_platform_o_auth_url_response_from_dict = GitHubPlatformOAuthUrlResponse.from_dict(git_hub_platform_o_auth_url_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


