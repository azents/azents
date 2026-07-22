# RuntimeProviderCredentialExchangeResponse

One-time Provider credential result returned to a controller operator.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**credential_id** | **str** |  | 
**provider_id** | **str** |  | 
**credential** | **str** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.runtime_provider_credential_exchange_response import RuntimeProviderCredentialExchangeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderCredentialExchangeResponse from a JSON string
runtime_provider_credential_exchange_response_instance = RuntimeProviderCredentialExchangeResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderCredentialExchangeResponse.to_json())

# convert the object into a dict
runtime_provider_credential_exchange_response_dict = runtime_provider_credential_exchange_response_instance.to_dict()
# create an instance of RuntimeProviderCredentialExchangeResponse from a dict
runtime_provider_credential_exchange_response_from_dict = RuntimeProviderCredentialExchangeResponse.from_dict(runtime_provider_credential_exchange_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


