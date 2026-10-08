# GitHubUserCandidateSummary

Verified account awaiting the manager's explicit confirmation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**attempt_id** | **str** |  | 
**account_id** | **int** |  | 
**account_login** | **str** |  | 
**account_avatar_url** | **str** |  | 
**app_id** | **str** |  | 
**source** | **str** |  | 
**sharing_scope** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_candidate_summary import GitHubUserCandidateSummary

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserCandidateSummary from a JSON string
git_hub_user_candidate_summary_instance = GitHubUserCandidateSummary.from_json(json)
# print the JSON string representation of the object
print(GitHubUserCandidateSummary.to_json())

# convert the object into a dict
git_hub_user_candidate_summary_dict = git_hub_user_candidate_summary_instance.to_dict()
# create an instance of GitHubUserCandidateSummary from a dict
git_hub_user_candidate_summary_from_dict = GitHubUserCandidateSummary.from_dict(git_hub_user_candidate_summary_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


