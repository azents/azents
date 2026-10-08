# GitHubSetupAvailability

Local registration availability, independent of provider health.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**platform** | **str** |  | 
**callback_url** | **str** |  | 
**user_tokens_must_not_expire** | **bool** |  | [optional] [default to True]

## Example

```python
from azentspublicclient.models.git_hub_setup_availability import GitHubSetupAvailability

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubSetupAvailability from a JSON string
git_hub_setup_availability_instance = GitHubSetupAvailability.from_json(json)
# print the JSON string representation of the object
print(GitHubSetupAvailability.to_json())

# convert the object into a dict
git_hub_setup_availability_dict = git_hub_setup_availability_instance.to_dict()
# create an instance of GitHubSetupAvailability from a dict
git_hub_setup_availability_from_dict = GitHubSetupAvailability.from_dict(git_hub_setup_availability_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


