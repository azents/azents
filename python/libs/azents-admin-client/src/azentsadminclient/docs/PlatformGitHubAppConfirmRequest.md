# PlatformGitHubAppConfirmRequest

Confirmation for an unchanged validated candidate impact.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**candidate_id** | **str** |  |
**expected_version** | **int** |  |
**confirmation_action** | **str** |  |

## Example

```python
from azentsadminclient.models.platform_git_hub_app_confirm_request import PlatformGitHubAppConfirmRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PlatformGitHubAppConfirmRequest from a JSON string
platform_git_hub_app_confirm_request_instance = PlatformGitHubAppConfirmRequest.from_json(json)
# print the JSON string representation of the object
print(PlatformGitHubAppConfirmRequest.to_json())

# convert the object into a dict
platform_git_hub_app_confirm_request_dict = platform_git_hub_app_confirm_request_instance.to_dict()
# create an instance of PlatformGitHubAppConfirmRequest from a dict
platform_git_hub_app_confirm_request_from_dict = PlatformGitHubAppConfirmRequest.from_dict(platform_git_hub_app_confirm_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
