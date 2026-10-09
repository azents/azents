# GitHubUserCreationReview

Verified account and desired nonsecret settings before publication.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**candidate** | [**GitHubUserCandidateSummary**](GitHubUserCandidateSummary.md) |  | 
**name** | **str** |  | 
**slug** | **str** |  | 
**description** | **str** |  | 
**prompt** | **str** |  | 
**config** | **object** |  | 
**enabled** | **bool** |  | 
**always_expose_tools** | **bool** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_creation_review import GitHubUserCreationReview

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserCreationReview from a JSON string
git_hub_user_creation_review_instance = GitHubUserCreationReview.from_json(json)
# print the JSON string representation of the object
print(GitHubUserCreationReview.to_json())

# convert the object into a dict
git_hub_user_creation_review_dict = git_hub_user_creation_review_instance.to_dict()
# create an instance of GitHubUserCreationReview from a dict
git_hub_user_creation_review_from_dict = GitHubUserCreationReview.from_dict(git_hub_user_creation_review_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


