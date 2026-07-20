# GitHubPlatformAuthorizationStateResponse

Redacted reconnect state for a Platform GitHub Toolkit.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**status** | **str** |  | 
**reason** | [**PlatformGitHubAppAuthorizationReason**](PlatformGitHubAppAuthorizationReason.md) |  | 

## Example

```python
from azentspublicclient.models.git_hub_platform_authorization_state_response import GitHubPlatformAuthorizationStateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubPlatformAuthorizationStateResponse from a JSON string
git_hub_platform_authorization_state_response_instance = GitHubPlatformAuthorizationStateResponse.from_json(json)
# print the JSON string representation of the object
print(GitHubPlatformAuthorizationStateResponse.to_json())

# convert the object into a dict
git_hub_platform_authorization_state_response_dict = git_hub_platform_authorization_state_response_instance.to_dict()
# create an instance of GitHubPlatformAuthorizationStateResponse from a dict
git_hub_platform_authorization_state_response_from_dict = GitHubPlatformAuthorizationStateResponse.from_dict(git_hub_platform_authorization_state_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


