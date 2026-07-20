# PlatformGitHubAppHealthResponse

Current-effective explicit health response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | [**SystemSettingHealthStatus**](SystemSettingHealthStatus.md) |  |
**code** | **str** |  |
**message** | **str** |  |
**action_hint** | **str** |  |
**metadata** | **Dict[str, object]** |  |
**checked_at** | **datetime** |  |

## Example

```python
from azentsadminclient.models.platform_git_hub_app_health_response import PlatformGitHubAppHealthResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PlatformGitHubAppHealthResponse from a JSON string
platform_git_hub_app_health_response_instance = PlatformGitHubAppHealthResponse.from_json(json)
# print the JSON string representation of the object
print(PlatformGitHubAppHealthResponse.to_json())

# convert the object into a dict
platform_git_hub_app_health_response_dict = platform_git_hub_app_health_response_instance.to_dict()
# create an instance of PlatformGitHubAppHealthResponse from a dict
platform_git_hub_app_health_response_from_dict = PlatformGitHubAppHealthResponse.from_dict(platform_git_hub_app_health_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
