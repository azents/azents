# GitHubUserConnectionSummaryResponse

Allowlisted user-account execution identity and cleanup readiness.

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
**cleanup_pending** | **bool** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_connection_summary_response import GitHubUserConnectionSummaryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserConnectionSummaryResponse from a JSON string
git_hub_user_connection_summary_response_instance = GitHubUserConnectionSummaryResponse.from_json(json)
# print the JSON string representation of the object
print(GitHubUserConnectionSummaryResponse.to_json())

# convert the object into a dict
git_hub_user_connection_summary_response_dict = git_hub_user_connection_summary_response_instance.to_dict()
# create an instance of GitHubUserConnectionSummaryResponse from a dict
git_hub_user_connection_summary_response_from_dict = GitHubUserConnectionSummaryResponse.from_dict(git_hub_user_connection_summary_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


