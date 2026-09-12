# AccountLinkCandidateCreatedResponse

One-time candidate response containing the plaintext code.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**origin_id** | **str** |  | 
**code** | **str** |  | 
**expires_at** | **datetime** |  | 
**status** | [**ExternalAccountLinkCandidateStatus**](ExternalAccountLinkCandidateStatus.md) |  | 

## Example

```python
from azentspublicclient.models.account_link_candidate_created_response import AccountLinkCandidateCreatedResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AccountLinkCandidateCreatedResponse from a JSON string
account_link_candidate_created_response_instance = AccountLinkCandidateCreatedResponse.from_json(json)
# print the JSON string representation of the object
print(AccountLinkCandidateCreatedResponse.to_json())

# convert the object into a dict
account_link_candidate_created_response_dict = account_link_candidate_created_response_instance.to_dict()
# create an instance of AccountLinkCandidateCreatedResponse from a dict
account_link_candidate_created_response_from_dict = AccountLinkCandidateCreatedResponse.from_dict(account_link_candidate_created_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


