# GitHubUserStatusOutput

Current connection plus cleanup status, never retired credential data.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**connection** | [**GitHubUserConnectionSummary**](GitHubUserConnectionSummary.md) |  | 
**cleanup_pending** | **bool** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_status_output import GitHubUserStatusOutput

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserStatusOutput from a JSON string
git_hub_user_status_output_instance = GitHubUserStatusOutput.from_json(json)
# print the JSON string representation of the object
print(GitHubUserStatusOutput.to_json())

# convert the object into a dict
git_hub_user_status_output_dict = git_hub_user_status_output_instance.to_dict()
# create an instance of GitHubUserStatusOutput from a dict
git_hub_user_status_output_from_dict = GitHubUserStatusOutput.from_dict(git_hub_user_status_output_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


