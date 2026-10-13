# GitHubSetupAppOutput


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**app** | [**GitHubSetupAppIdentity**](GitHubSetupAppIdentity.md) |  | 

## Example

```python
from azentspublicclient.models.git_hub_setup_app_output import GitHubSetupAppOutput

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubSetupAppOutput from a JSON string
git_hub_setup_app_output_instance = GitHubSetupAppOutput.from_json(json)
# print the JSON string representation of the object
print(GitHubSetupAppOutput.to_json())

# convert the object into a dict
git_hub_setup_app_output_dict = git_hub_setup_app_output_instance.to_dict()
# create an instance of GitHubSetupAppOutput from a dict
git_hub_setup_app_output_from_dict = GitHubSetupAppOutput.from_dict(git_hub_setup_app_output_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


