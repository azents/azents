# LLMProviderCapabilityListResponse

Available LLM provider capability list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[LLMProviderCapabilityResponse]**](LLMProviderCapabilityResponse.md) |  | 

## Example

```python
from azentspublicclient.models.llm_provider_capability_list_response import LLMProviderCapabilityListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of LLMProviderCapabilityListResponse from a JSON string
llm_provider_capability_list_response_instance = LLMProviderCapabilityListResponse.from_json(json)
# print the JSON string representation of the object
print(LLMProviderCapabilityListResponse.to_json())

# convert the object into a dict
llm_provider_capability_list_response_dict = llm_provider_capability_list_response_instance.to_dict()
# create an instance of LLMProviderCapabilityListResponse from a dict
llm_provider_capability_list_response_from_dict = LLMProviderCapabilityListResponse.from_dict(llm_provider_capability_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


