# PlatformGitHubAppPatchRequest

Optimistic partial update for the Platform GitHub App Admin base.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**app_id** | **str** |  | [optional] 
**client_id** | **str** |  | [optional] 
**private_key** | [**SystemSettingSecretActionRequest**](SystemSettingSecretActionRequest.md) |  | [optional] 
**client_secret** | [**SystemSettingSecretActionRequest**](SystemSettingSecretActionRequest.md) |  | [optional] 

## Example

```python
from azentsadminclient.models.platform_git_hub_app_patch_request import PlatformGitHubAppPatchRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PlatformGitHubAppPatchRequest from a JSON string
platform_git_hub_app_patch_request_instance = PlatformGitHubAppPatchRequest.from_json(json)
# print the JSON string representation of the object
print(PlatformGitHubAppPatchRequest.to_json())

# convert the object into a dict
platform_git_hub_app_patch_request_dict = platform_git_hub_app_patch_request_instance.to_dict()
# create an instance of PlatformGitHubAppPatchRequest from a dict
platform_git_hub_app_patch_request_from_dict = PlatformGitHubAppPatchRequest.from_dict(platform_git_hub_app_patch_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


