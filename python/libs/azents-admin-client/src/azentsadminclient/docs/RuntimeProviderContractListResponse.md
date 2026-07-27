# RuntimeProviderContractListResponse

Provider contract revision history.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[RuntimeProviderContractResponse]**](RuntimeProviderContractResponse.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_contract_list_response import RuntimeProviderContractListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderContractListResponse from a JSON string
runtime_provider_contract_list_response_instance = RuntimeProviderContractListResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderContractListResponse.to_json())

# convert the object into a dict
runtime_provider_contract_list_response_dict = runtime_provider_contract_list_response_instance.to_dict()
# create an instance of RuntimeProviderContractListResponse from a dict
runtime_provider_contract_list_response_from_dict = RuntimeProviderContractListResponse.from_dict(runtime_provider_contract_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


