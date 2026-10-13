# GitHubUserCreationConfirmRequest

Exact creation attempt plus complete final reviewed settings.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**attempt_id** | **str** |  | 
**settings** | [**GitHubUserCreationFinalSettings**](GitHubUserCreationFinalSettings.md) |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_creation_confirm_request import GitHubUserCreationConfirmRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserCreationConfirmRequest from a JSON string
git_hub_user_creation_confirm_request_instance = GitHubUserCreationConfirmRequest.from_json(json)
# print the JSON string representation of the object
print(GitHubUserCreationConfirmRequest.to_json())

# convert the object into a dict
git_hub_user_creation_confirm_request_dict = git_hub_user_creation_confirm_request_instance.to_dict()
# create an instance of GitHubUserCreationConfirmRequest from a dict
git_hub_user_creation_confirm_request_from_dict = GitHubUserCreationConfirmRequest.from_dict(git_hub_user_creation_confirm_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


