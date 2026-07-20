# PlatformGitHubAppBindingResponse

Redacted resources that require reconnect for the effective App.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**affected_user_count** | **int** |  | 
**affected_installation_count** | **int** |  | 
**affected_toolkit_count** | **int** |  | 
**affected_agent_count** | **int** |  | 

## Example

```python
from azentsadminclient.models.platform_git_hub_app_binding_response import PlatformGitHubAppBindingResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PlatformGitHubAppBindingResponse from a JSON string
platform_git_hub_app_binding_response_instance = PlatformGitHubAppBindingResponse.from_json(json)
# print the JSON string representation of the object
print(PlatformGitHubAppBindingResponse.to_json())

# convert the object into a dict
platform_git_hub_app_binding_response_dict = platform_git_hub_app_binding_response_instance.to_dict()
# create an instance of PlatformGitHubAppBindingResponse from a dict
platform_git_hub_app_binding_response_from_dict = PlatformGitHubAppBindingResponse.from_dict(platform_git_hub_app_binding_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


