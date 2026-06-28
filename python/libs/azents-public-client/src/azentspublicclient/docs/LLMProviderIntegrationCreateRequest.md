# LLMProviderIntegrationCreateRequest

LLM Provider Integration creation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | [**LLMProvider**](LLMProvider.md) | LLM Hosting provider |
**name** | **str** |  | [optional]
**secrets** | [**Secrets**](Secrets.md) |  |
**config** | [**LLMProviderIntegrationCreateRequestConfig**](LLMProviderIntegrationCreateRequestConfig.md) |  | [optional]
**enabled** | **bool** | Enabled state | [optional] [default to True]

## Example

```python
from azentspublicclient.models.llm_provider_integration_create_request import LLMProviderIntegrationCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of LLMProviderIntegrationCreateRequest from a JSON string
llm_provider_integration_create_request_instance = LLMProviderIntegrationCreateRequest.from_json(json)
# print the JSON string representation of the object
print(LLMProviderIntegrationCreateRequest.to_json())

# convert the object into a dict
llm_provider_integration_create_request_dict = llm_provider_integration_create_request_instance.to_dict()
# create an instance of LLMProviderIntegrationCreateRequest from a dict
llm_provider_integration_create_request_from_dict = LLMProviderIntegrationCreateRequest.from_dict(llm_provider_integration_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


