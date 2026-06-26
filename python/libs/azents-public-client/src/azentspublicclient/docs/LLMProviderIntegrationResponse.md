# LLMProviderIntegrationResponse

LLM Provider Integration response without secrets.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**provider** | [**LLMProvider**](LLMProvider.md) |  | 
**name** | **str** |  | 
**config** | [**LLMProviderIntegrationCreateRequestConfig**](LLMProviderIntegrationCreateRequestConfig.md) |  | 
**enabled** | **bool** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.llm_provider_integration_response import LLMProviderIntegrationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of LLMProviderIntegrationResponse from a JSON string
llm_provider_integration_response_instance = LLMProviderIntegrationResponse.from_json(json)
# print the JSON string representation of the object
print(LLMProviderIntegrationResponse.to_json())

# convert the object into a dict
llm_provider_integration_response_dict = llm_provider_integration_response_instance.to_dict()
# create an instance of LLMProviderIntegrationResponse from a dict
llm_provider_integration_response_from_dict = LLMProviderIntegrationResponse.from_dict(llm_provider_integration_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


