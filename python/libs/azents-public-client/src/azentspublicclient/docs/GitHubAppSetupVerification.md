# GitHubAppSetupVerification


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**github_auth_type** | **str** |  | 
**transport** | [**GitHubSetupTransport**](GitHubSetupTransport.md) |  | 
**app_id** | **str** |  | 
**private_key** | **str** |  | 
**installation_ids** | **List[str]** |  | 

## Example

```python
from azentspublicclient.models.git_hub_app_setup_verification import GitHubAppSetupVerification

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubAppSetupVerification from a JSON string
git_hub_app_setup_verification_instance = GitHubAppSetupVerification.from_json(json)
# print the JSON string representation of the object
print(GitHubAppSetupVerification.to_json())

# convert the object into a dict
git_hub_app_setup_verification_dict = git_hub_app_setup_verification_instance.to_dict()
# create an instance of GitHubAppSetupVerification from a dict
git_hub_app_setup_verification_from_dict = GitHubAppSetupVerification.from_dict(git_hub_app_setup_verification_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


