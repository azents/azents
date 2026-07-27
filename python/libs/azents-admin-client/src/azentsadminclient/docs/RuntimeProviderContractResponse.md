# RuntimeProviderContractResponse

One immutable Provider capability contract revision.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**digest** | **str** |  | 
**implementation_version** | **str** |  | 
**protocol_version** | **str** |  | 
**contract** | **object** |  | 
**compatibility** | **object** |  | 
**status** | [**RuntimeProviderContractStatus**](RuntimeProviderContractStatus.md) |  | 
**validation_code** | **str** |  | 
**validation_message** | **str** |  | 
**accepted_by_user_id** | **str** |  | 
**accepted_at** | **datetime** |  | 
**created_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_contract_response import RuntimeProviderContractResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderContractResponse from a JSON string
runtime_provider_contract_response_instance = RuntimeProviderContractResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderContractResponse.to_json())

# convert the object into a dict
runtime_provider_contract_response_dict = runtime_provider_contract_response_instance.to_dict()
# create an instance of RuntimeProviderContractResponse from a dict
runtime_provider_contract_response_from_dict = RuntimeProviderContractResponse.from_dict(runtime_provider_contract_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


