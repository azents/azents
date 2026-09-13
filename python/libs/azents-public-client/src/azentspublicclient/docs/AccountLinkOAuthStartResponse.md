# AccountLinkOAuthStartResponse

Fixed-provider authorization URL for one durable OAuth attempt.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**authorization_url** | **str** |  | 

## Example

```python
from azentspublicclient.models.account_link_o_auth_start_response import AccountLinkOAuthStartResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AccountLinkOAuthStartResponse from a JSON string
account_link_o_auth_start_response_instance = AccountLinkOAuthStartResponse.from_json(json)
# print the JSON string representation of the object
print(AccountLinkOAuthStartResponse.to_json())

# convert the object into a dict
account_link_o_auth_start_response_dict = account_link_o_auth_start_response_instance.to_dict()
# create an instance of AccountLinkOAuthStartResponse from a dict
account_link_o_auth_start_response_from_dict = AccountLinkOAuthStartResponse.from_dict(account_link_o_auth_start_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


