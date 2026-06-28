# ModelCapabilities

Normalized LLM model capability contract.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**context_window** | [**ModelContextWindow**](ModelContextWindow.md) |  | [optional]
**modalities** | [**ModelModalities**](ModelModalities.md) |  | [optional]
**tool_calling** | [**ModelToolCallingCapabilities**](ModelToolCallingCapabilities.md) |  | [optional]
**reasoning** | [**ModelReasoningCapabilities**](ModelReasoningCapabilities.md) |  | [optional]
**built_in_tools** | [**ModelBuiltInToolCapabilities**](ModelBuiltInToolCapabilities.md) |  | [optional]
**parameters** | [**ModelParameterCapabilities**](ModelParameterCapabilities.md) |  | [optional]
**compatibility** | [**ModelCompatibilityCapabilities**](ModelCompatibilityCapabilities.md) |  | [optional]

## Example

```python
from azentspublicclient.models.model_capabilities import ModelCapabilities

# TODO update the JSON string below
json = "{}"
# create an instance of ModelCapabilities from a JSON string
model_capabilities_instance = ModelCapabilities.from_json(json)
# print the JSON string representation of the object
print(ModelCapabilities.to_json())

# convert the object into a dict
model_capabilities_dict = model_capabilities_instance.to_dict()
# create an instance of ModelCapabilities from a dict
model_capabilities_from_dict = ModelCapabilities.from_dict(model_capabilities_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


