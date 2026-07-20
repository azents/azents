# PlatformGitHubAppCandidateResponse

Redacted candidate lifecycle response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  |
**base_version** | **int** |  |
**validation_status** | [**SystemSettingValidationStatus**](SystemSettingValidationStatus.md) |  |
**validation_code** | **str** |  |
**validation_message** | **str** |  |
**action_hint** | **str** |  |
**impact** | **Dict[str, object]** |  |
**created_at** | **datetime** |  |
**updated_at** | **datetime** |  |
**expires_at** | **datetime** |  |

## Example

```python
from azentsadminclient.models.platform_git_hub_app_candidate_response import PlatformGitHubAppCandidateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PlatformGitHubAppCandidateResponse from a JSON string
platform_git_hub_app_candidate_response_instance = PlatformGitHubAppCandidateResponse.from_json(json)
# print the JSON string representation of the object
print(PlatformGitHubAppCandidateResponse.to_json())

# convert the object into a dict
platform_git_hub_app_candidate_response_dict = platform_git_hub_app_candidate_response_instance.to_dict()
# create an instance of PlatformGitHubAppCandidateResponse from a dict
platform_git_hub_app_candidate_response_from_dict = PlatformGitHubAppCandidateResponse.from_dict(platform_git_hub_app_candidate_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
