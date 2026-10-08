# GitHubUserConnectionSummary

Allowlisted public metadata without access or client credentials.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**account_id** | **int** |  | 
**account_login** | **str** |  | 
**account_avatar_url** | **str** |  | 
**app_id** | **str** |  | 
**source** | **str** |  | 
**status** | [**GitHubUserConnectionStatus**](GitHubUserConnectionStatus.md) |  | 
**failure_reason** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_connection_summary import GitHubUserConnectionSummary

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserConnectionSummary from a JSON string
git_hub_user_connection_summary_instance = GitHubUserConnectionSummary.from_json(json)
# print the JSON string representation of the object
print(GitHubUserConnectionSummary.to_json())

# convert the object into a dict
git_hub_user_connection_summary_dict = git_hub_user_connection_summary_instance.to_dict()
# create an instance of GitHubUserConnectionSummary from a dict
git_hub_user_connection_summary_from_dict = GitHubUserConnectionSummary.from_dict(git_hub_user_connection_summary_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


