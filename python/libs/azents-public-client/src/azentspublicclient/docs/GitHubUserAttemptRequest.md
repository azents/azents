# GitHubUserAttemptRequest

Exact local attempt for confirm or cancellation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**attempt_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_attempt_request import GitHubUserAttemptRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserAttemptRequest from a JSON string
git_hub_user_attempt_request_instance = GitHubUserAttemptRequest.from_json(json)
# print the JSON string representation of the object
print(GitHubUserAttemptRequest.to_json())

# convert the object into a dict
git_hub_user_attempt_request_dict = git_hub_user_attempt_request_instance.to_dict()
# create an instance of GitHubUserAttemptRequest from a dict
git_hub_user_attempt_request_from_dict = GitHubUserAttemptRequest.from_dict(git_hub_user_attempt_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


