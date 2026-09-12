# AccountLinkReturnContextResponse

Sanitized provider-native return navigation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**kind** | [**ExternalAccountLinkReturnKind**](ExternalAccountLinkReturnKind.md) |  | 
**provider_tenant_display_label** | **str** |  | 
**provider_url** | **str** |  | 

## Example

```python
from azentspublicclient.models.account_link_return_context_response import AccountLinkReturnContextResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AccountLinkReturnContextResponse from a JSON string
account_link_return_context_response_instance = AccountLinkReturnContextResponse.from_json(json)
# print the JSON string representation of the object
print(AccountLinkReturnContextResponse.to_json())

# convert the object into a dict
account_link_return_context_response_dict = account_link_return_context_response_instance.to_dict()
# create an instance of AccountLinkReturnContextResponse from a dict
account_link_return_context_response_from_dict = AccountLinkReturnContextResponse.from_dict(account_link_return_context_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


