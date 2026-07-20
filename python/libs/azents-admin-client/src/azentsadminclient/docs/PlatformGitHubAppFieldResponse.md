# PlatformGitHubAppFieldResponse

Redacted field response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  |
**secret** | **bool** |  |
**value** | **str** |  |
**configured** | **bool** |  |
**source** | [**SystemSettingFieldSource**](SystemSettingFieldSource.md) |  |
**environment_variable** | **str** |  |
**fallback_configured** | **bool** |  |
**fallback_last_changed_at** | **datetime** |  |

## Example

```python
from azentsadminclient.models.platform_git_hub_app_field_response import PlatformGitHubAppFieldResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PlatformGitHubAppFieldResponse from a JSON string
platform_git_hub_app_field_response_instance = PlatformGitHubAppFieldResponse.from_json(json)
# print the JSON string representation of the object
print(PlatformGitHubAppFieldResponse.to_json())

# convert the object into a dict
platform_git_hub_app_field_response_dict = platform_git_hub_app_field_response_instance.to_dict()
# create an instance of PlatformGitHubAppFieldResponse from a dict
platform_git_hub_app_field_response_from_dict = PlatformGitHubAppFieldResponse.from_dict(platform_git_hub_app_field_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
