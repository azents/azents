# RuntimeProviderCredentialExchangeRequest

One-time enrollment grant exchange input.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**grant_id** | **str** |  | 
**secret** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_provider_credential_exchange_request import RuntimeProviderCredentialExchangeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderCredentialExchangeRequest from a JSON string
runtime_provider_credential_exchange_request_instance = RuntimeProviderCredentialExchangeRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderCredentialExchangeRequest.to_json())

# convert the object into a dict
runtime_provider_credential_exchange_request_dict = runtime_provider_credential_exchange_request_instance.to_dict()
# create an instance of RuntimeProviderCredentialExchangeRequest from a dict
runtime_provider_credential_exchange_request_from_dict = RuntimeProviderCredentialExchangeRequest.from_dict(runtime_provider_credential_exchange_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


