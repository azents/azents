# RuntimeProviderContractAcceptRequest

Optimistic concurrency input for explicit contract acceptance.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_admin_version** | **int** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_contract_accept_request import RuntimeProviderContractAcceptRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderContractAcceptRequest from a JSON string
runtime_provider_contract_accept_request_instance = RuntimeProviderContractAcceptRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderContractAcceptRequest.to_json())

# convert the object into a dict
runtime_provider_contract_accept_request_dict = runtime_provider_contract_accept_request_instance.to_dict()
# create an instance of RuntimeProviderContractAcceptRequest from a dict
runtime_provider_contract_accept_request_from_dict = RuntimeProviderContractAcceptRequest.from_dict(runtime_provider_contract_accept_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


