# LLMProviderIntegrationUpdateRequest

LLM Provider Integration update request for partial updates.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Display name | [optional] 
**secrets** | [**Secrets1**](Secrets1.md) |  | [optional] 
**config** | [**LLMProviderIntegrationCreateRequestConfig**](LLMProviderIntegrationCreateRequestConfig.md) |  | [optional] 
**enabled** | **bool** | Enabled flag | [optional] 

## Example

```python
from azentspublicclient.models.llm_provider_integration_update_request import LLMProviderIntegrationUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of LLMProviderIntegrationUpdateRequest from a JSON string
llm_provider_integration_update_request_instance = LLMProviderIntegrationUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(LLMProviderIntegrationUpdateRequest.to_json())

# convert the object into a dict
llm_provider_integration_update_request_dict = llm_provider_integration_update_request_instance.to_dict()
# create an instance of LLMProviderIntegrationUpdateRequest from a dict
llm_provider_integration_update_request_from_dict = LLMProviderIntegrationUpdateRequest.from_dict(llm_provider_integration_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


