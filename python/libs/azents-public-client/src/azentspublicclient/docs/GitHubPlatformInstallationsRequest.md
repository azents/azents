# GitHubPlatformInstallationsRequest

GitHub Platform App installation list request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**code** | **str** | GitHub OAuth authorization code | 
**state** | **str** | OAuth state parameter for CSRF validation | 

## Example

```python
from azentspublicclient.models.git_hub_platform_installations_request import GitHubPlatformInstallationsRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubPlatformInstallationsRequest from a JSON string
git_hub_platform_installations_request_instance = GitHubPlatformInstallationsRequest.from_json(json)
# print the JSON string representation of the object
print(GitHubPlatformInstallationsRequest.to_json())

# convert the object into a dict
git_hub_platform_installations_request_dict = git_hub_platform_installations_request_instance.to_dict()
# create an instance of GitHubPlatformInstallationsRequest from a dict
git_hub_platform_installations_request_from_dict = GitHubPlatformInstallationsRequest.from_dict(git_hub_platform_installations_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


