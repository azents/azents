# AccountLinkProviderAvailabilityListResponse

Redacted provider availability list.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[AccountLinkProviderAvailabilityResponse]**](AccountLinkProviderAvailabilityResponse.md) |  | 

## Example

```python
from azentspublicclient.models.account_link_provider_availability_list_response import AccountLinkProviderAvailabilityListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AccountLinkProviderAvailabilityListResponse from a JSON string
account_link_provider_availability_list_response_instance = AccountLinkProviderAvailabilityListResponse.from_json(json)
# print the JSON string representation of the object
print(AccountLinkProviderAvailabilityListResponse.to_json())

# convert the object into a dict
account_link_provider_availability_list_response_dict = account_link_provider_availability_list_response_instance.to_dict()
# create an instance of AccountLinkProviderAvailabilityListResponse from a dict
account_link_provider_availability_list_response_from_dict = AccountLinkProviderAvailabilityListResponse.from_dict(account_link_provider_availability_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


