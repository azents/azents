# AccountLinkCandidateResponse

Status-only immutable candidate response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**origin_id** | **str** |  | 
**expires_at** | **datetime** |  | 
**status** | [**ExternalAccountLinkCandidateStatus**](ExternalAccountLinkCandidateStatus.md) |  | 
**link_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.account_link_candidate_response import AccountLinkCandidateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AccountLinkCandidateResponse from a JSON string
account_link_candidate_response_instance = AccountLinkCandidateResponse.from_json(json)
# print the JSON string representation of the object
print(AccountLinkCandidateResponse.to_json())

# convert the object into a dict
account_link_candidate_response_dict = account_link_candidate_response_instance.to_dict()
# create an instance of AccountLinkCandidateResponse from a dict
account_link_candidate_response_from_dict = AccountLinkCandidateResponse.from_dict(account_link_candidate_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


