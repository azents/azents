# PlatformGitHubAppDetailResponse

Redacted Platform GitHub App detail response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**section** | **str** |  |
**schema_version** | **int** |  |
**admin_version** | **int** |  |
**effective_status** | [**PlatformGitHubAppEffectiveStatus**](PlatformGitHubAppEffectiveStatus.md) |  |
**fields** | [**List[PlatformGitHubAppFieldResponse]**](PlatformGitHubAppFieldResponse.md) |  |
**candidate** | [**PlatformGitHubAppCandidateResponse**](PlatformGitHubAppCandidateResponse.md) |  |
**health** | [**PlatformGitHubAppHealthResponse**](PlatformGitHubAppHealthResponse.md) |  |
**binding_impact** | [**PlatformGitHubAppBindingResponse**](PlatformGitHubAppBindingResponse.md) |  |
**activation_validation_status** | [**SystemSettingValidationStatus**](SystemSettingValidationStatus.md) |  |
**app_slug** | **str** |  |

## Example

```python
from azentsadminclient.models.platform_git_hub_app_detail_response import PlatformGitHubAppDetailResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PlatformGitHubAppDetailResponse from a JSON string
platform_git_hub_app_detail_response_instance = PlatformGitHubAppDetailResponse.from_json(json)
# print the JSON string representation of the object
print(PlatformGitHubAppDetailResponse.to_json())

# convert the object into a dict
platform_git_hub_app_detail_response_dict = platform_git_hub_app_detail_response_instance.to_dict()
# create an instance of PlatformGitHubAppDetailResponse from a dict
platform_git_hub_app_detail_response_from_dict = PlatformGitHubAppDetailResponse.from_dict(platform_git_hub_app_detail_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
