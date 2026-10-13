# GitHubSetupUserIdentity


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**id** | **int** |  | 
**login** | **str** |  | 
**avatar_url** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_setup_user_identity import GitHubSetupUserIdentity

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubSetupUserIdentity from a JSON string
git_hub_setup_user_identity_instance = GitHubSetupUserIdentity.from_json(json)
# print the JSON string representation of the object
print(GitHubSetupUserIdentity.to_json())

# convert the object into a dict
git_hub_setup_user_identity_dict = git_hub_setup_user_identity_instance.to_dict()
# create an instance of GitHubSetupUserIdentity from a dict
git_hub_setup_user_identity_from_dict = GitHubSetupUserIdentity.from_dict(git_hub_setup_user_identity_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


