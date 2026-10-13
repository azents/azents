# GitHubSetupAppVerifiedIdentity


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**app_id** | **str** |  | 
**name** | **str** |  | 
**slug** | **str** |  | 
**type** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_setup_app_verified_identity import GitHubSetupAppVerifiedIdentity

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubSetupAppVerifiedIdentity from a JSON string
git_hub_setup_app_verified_identity_instance = GitHubSetupAppVerifiedIdentity.from_json(json)
# print the JSON string representation of the object
print(GitHubSetupAppVerifiedIdentity.to_json())

# convert the object into a dict
git_hub_setup_app_verified_identity_dict = git_hub_setup_app_verified_identity_instance.to_dict()
# create an instance of GitHubSetupAppVerifiedIdentity from a dict
git_hub_setup_app_verified_identity_from_dict = GitHubSetupAppVerifiedIdentity.from_dict(git_hub_setup_app_verified_identity_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


