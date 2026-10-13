# GitHubSetupVerificationOutput


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**identity** | [**Identity**](Identity.md) |  | 
**installations** | [**List[GitHubSetupInstallationObservation]**](GitHubSetupInstallationObservation.md) |  | 
**connectivity** | [**GitHubSetupConnectivity**](GitHubSetupConnectivity.md) |  | 

## Example

```python
from azentspublicclient.models.git_hub_setup_verification_output import GitHubSetupVerificationOutput

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubSetupVerificationOutput from a JSON string
git_hub_setup_verification_output_instance = GitHubSetupVerificationOutput.from_json(json)
# print the JSON string representation of the object
print(GitHubSetupVerificationOutput.to_json())

# convert the object into a dict
git_hub_setup_verification_output_dict = git_hub_setup_verification_output_instance.to_dict()
# create an instance of GitHubSetupVerificationOutput from a dict
git_hub_setup_verification_output_from_dict = GitHubSetupVerificationOutput.from_dict(git_hub_setup_verification_output_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


