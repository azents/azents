# GitHubUserExchangeRequest

Transient provider callback inputs excluded from model representations.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**code** | **str** |  | 
**state** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_exchange_request import GitHubUserExchangeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserExchangeRequest from a JSON string
git_hub_user_exchange_request_instance = GitHubUserExchangeRequest.from_json(json)
# print the JSON string representation of the object
print(GitHubUserExchangeRequest.to_json())

# convert the object into a dict
git_hub_user_exchange_request_dict = git_hub_user_exchange_request_instance.to_dict()
# create an instance of GitHubUserExchangeRequest from a dict
git_hub_user_exchange_request_from_dict = GitHubUserExchangeRequest.from_dict(git_hub_user_exchange_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


