# LLMProviderCapabilityResponse

LLM provider capability exposed to the workspace UI.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | [**LLMProvider**](LLMProvider.md) |  | 
**display_name** | **str** |  | 
**credential_type** | **str** |  | 
**experimental** | **bool** |  | [optional] [default to False]

## Example

```python
from azentspublicclient.models.llm_provider_capability_response import LLMProviderCapabilityResponse

# TODO update the JSON string below
json = "{}"
# create an instance of LLMProviderCapabilityResponse from a JSON string
llm_provider_capability_response_instance = LLMProviderCapabilityResponse.from_json(json)
# print the JSON string representation of the object
print(LLMProviderCapabilityResponse.to_json())

# convert the object into a dict
llm_provider_capability_response_dict = llm_provider_capability_response_instance.to_dict()
# create an instance of LLMProviderCapabilityResponse from a dict
llm_provider_capability_response_from_dict = LLMProviderCapabilityResponse.from_dict(llm_provider_capability_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


