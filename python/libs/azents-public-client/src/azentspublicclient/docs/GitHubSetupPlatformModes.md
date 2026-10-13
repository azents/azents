# GitHubSetupPlatformModes

Local readiness for the two supported Platform authentication paths.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**user_account** | **str** |  | 
**installation** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_setup_platform_modes import GitHubSetupPlatformModes

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubSetupPlatformModes from a JSON string
git_hub_setup_platform_modes_instance = GitHubSetupPlatformModes.from_json(json)
# print the JSON string representation of the object
print(GitHubSetupPlatformModes.to_json())

# convert the object into a dict
git_hub_setup_platform_modes_dict = git_hub_setup_platform_modes_instance.to_dict()
# create an instance of GitHubSetupPlatformModes from a dict
git_hub_setup_platform_modes_from_dict = GitHubSetupPlatformModes.from_dict(git_hub_setup_platform_modes_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


