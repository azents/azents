# GitHubUserCreationFinalSettings

Complete final non-authentication input, never an attempt-settings patch.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**toolsets** | **List[str]** |  | 
**timeout** | **float** |  | 
**name** | **str** |  | 
**slug** | **str** |  | 
**description** | **str** |  | 
**prompt** | **str** |  | 
**enabled** | **bool** |  | 
**always_expose_tools** | **bool** |  | 
**inject_runtime_environment** | **bool** |  | 
**runtime_risk_acknowledged** | **bool** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_creation_final_settings import GitHubUserCreationFinalSettings

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserCreationFinalSettings from a JSON string
git_hub_user_creation_final_settings_instance = GitHubUserCreationFinalSettings.from_json(json)
# print the JSON string representation of the object
print(GitHubUserCreationFinalSettings.to_json())

# convert the object into a dict
git_hub_user_creation_final_settings_dict = git_hub_user_creation_final_settings_instance.to_dict()
# create an instance of GitHubUserCreationFinalSettings from a dict
git_hub_user_creation_final_settings_from_dict = GitHubUserCreationFinalSettings.from_dict(git_hub_user_creation_final_settings_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


