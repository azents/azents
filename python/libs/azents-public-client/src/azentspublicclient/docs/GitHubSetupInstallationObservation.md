# GitHubSetupInstallationObservation


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**installation_id** | **str** |  | 
**account_login** | **str** |  | 
**account_type** | **str** |  | 
**account_avatar_url** | **str** |  | 
**status** | **str** |  | 
**message** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_setup_installation_observation import GitHubSetupInstallationObservation

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubSetupInstallationObservation from a JSON string
git_hub_setup_installation_observation_instance = GitHubSetupInstallationObservation.from_json(json)
# print the JSON string representation of the object
print(GitHubSetupInstallationObservation.to_json())

# convert the object into a dict
git_hub_setup_installation_observation_dict = git_hub_setup_installation_observation_instance.to_dict()
# create an instance of GitHubSetupInstallationObservation from a dict
git_hub_setup_installation_observation_from_dict = GitHubSetupInstallationObservation.from_dict(git_hub_setup_installation_observation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


