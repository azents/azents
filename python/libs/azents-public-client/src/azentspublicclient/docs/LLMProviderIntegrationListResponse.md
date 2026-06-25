# LLMProviderIntegrationListResponse

LLM Provider Integration list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[LLMProviderIntegrationResponse]**](LLMProviderIntegrationResponse.md) |  | 

## Example

```python
from azentspublicclient.models.llm_provider_integration_list_response import LLMProviderIntegrationListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of LLMProviderIntegrationListResponse from a JSON string
llm_provider_integration_list_response_instance = LLMProviderIntegrationListResponse.from_json(json)
# print the JSON string representation of the object
print(LLMProviderIntegrationListResponse.to_json())

# convert the object into a dict
llm_provider_integration_list_response_dict = llm_provider_integration_list_response_instance.to_dict()
# create an instance of LLMProviderIntegrationListResponse from a dict
llm_provider_integration_list_response_from_dict = LLMProviderIntegrationListResponse.from_dict(llm_provider_integration_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


