# AccountLinkOAuthExchangeRequest

Authenticated callback exchange payload.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**code** | **str** |  | 
**state** | **str** |  | 

## Example

```python
from azentspublicclient.models.account_link_o_auth_exchange_request import AccountLinkOAuthExchangeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AccountLinkOAuthExchangeRequest from a JSON string
account_link_o_auth_exchange_request_instance = AccountLinkOAuthExchangeRequest.from_json(json)
# print the JSON string representation of the object
print(AccountLinkOAuthExchangeRequest.to_json())

# convert the object into a dict
account_link_o_auth_exchange_request_dict = account_link_o_auth_exchange_request_instance.to_dict()
# create an instance of AccountLinkOAuthExchangeRequest from a dict
account_link_o_auth_exchange_request_from_dict = AccountLinkOAuthExchangeRequest.from_dict(account_link_o_auth_exchange_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


