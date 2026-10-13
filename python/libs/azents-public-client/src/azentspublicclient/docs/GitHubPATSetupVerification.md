# GitHubPATSetupVerification


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**github_auth_type** | **str** |  | 
**transport** | [**GitHubSetupTransport**](GitHubSetupTransport.md) |  | 
**token** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_pat_setup_verification import GitHubPATSetupVerification

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubPATSetupVerification from a JSON string
git_hub_pat_setup_verification_instance = GitHubPATSetupVerification.from_json(json)
# print the JSON string representation of the object
print(GitHubPATSetupVerification.to_json())

# convert the object into a dict
git_hub_pat_setup_verification_dict = git_hub_pat_setup_verification_instance.to_dict()
# create an instance of GitHubPATSetupVerification from a dict
git_hub_pat_setup_verification_from_dict = GitHubPATSetupVerification.from_dict(git_hub_pat_setup_verification_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


