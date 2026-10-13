# GitHubSetupAppIdentity


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**app_id** | **str** |  | 
**name** | **str** |  | 
**slug** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_setup_app_identity import GitHubSetupAppIdentity

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubSetupAppIdentity from a JSON string
git_hub_setup_app_identity_instance = GitHubSetupAppIdentity.from_json(json)
# print the JSON string representation of the object
print(GitHubSetupAppIdentity.to_json())

# convert the object into a dict
git_hub_setup_app_identity_dict = git_hub_setup_app_identity_instance.to_dict()
# create an instance of GitHubSetupAppIdentity from a dict
git_hub_setup_app_identity_from_dict = GitHubSetupAppIdentity.from_dict(git_hub_setup_app_identity_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


