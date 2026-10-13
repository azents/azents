# GitHubPlatformSetupVerification


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**github_auth_type** | **str** |  | 
**transport** | [**GitHubSetupTransport**](GitHubSetupTransport.md) |  | 
**installation_ids** | **List[str]** |  | 

## Example

```python
from azentspublicclient.models.git_hub_platform_setup_verification import GitHubPlatformSetupVerification

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubPlatformSetupVerification from a JSON string
git_hub_platform_setup_verification_instance = GitHubPlatformSetupVerification.from_json(json)
# print the JSON string representation of the object
print(GitHubPlatformSetupVerification.to_json())

# convert the object into a dict
git_hub_platform_setup_verification_dict = git_hub_platform_setup_verification_instance.to_dict()
# create an instance of GitHubPlatformSetupVerification from a dict
git_hub_platform_setup_verification_from_dict = GitHubPlatformSetupVerification.from_dict(git_hub_platform_setup_verification_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


