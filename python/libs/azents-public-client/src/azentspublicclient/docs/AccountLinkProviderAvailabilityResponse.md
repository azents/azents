# AccountLinkProviderAvailabilityResponse

Redacted availability of one provider identity OAuth Section.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) |  | 
**status** | [**ExternalAccountOAuthEffectiveStatus**](ExternalAccountOAuthEffectiveStatus.md) |  | 
**available** | **bool** |  | 
**callback_url** | **str** |  | 

## Example

```python
from azentspublicclient.models.account_link_provider_availability_response import AccountLinkProviderAvailabilityResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AccountLinkProviderAvailabilityResponse from a JSON string
account_link_provider_availability_response_instance = AccountLinkProviderAvailabilityResponse.from_json(json)
# print the JSON string representation of the object
print(AccountLinkProviderAvailabilityResponse.to_json())

# convert the object into a dict
account_link_provider_availability_response_dict = account_link_provider_availability_response_instance.to_dict()
# create an instance of AccountLinkProviderAvailabilityResponse from a dict
account_link_provider_availability_response_from_dict = AccountLinkProviderAvailabilityResponse.from_dict(account_link_provider_availability_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


