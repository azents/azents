# ModelReasoningCapabilities

Represents reasoning capability.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**supported** | **bool** |  | [optional] [default to False]
**effort_levels** | [**List[ModelReasoningEffort]**](ModelReasoningEffort.md) |  | [optional]
**summaries** | **bool** |  | [optional]

## Example

```python
from azentspublicclient.models.model_reasoning_capabilities import ModelReasoningCapabilities

# TODO update the JSON string below
json = "{}"
# create an instance of ModelReasoningCapabilities from a JSON string
model_reasoning_capabilities_instance = ModelReasoningCapabilities.from_json(json)
# print the JSON string representation of the object
print(ModelReasoningCapabilities.to_json())

# convert the object into a dict
model_reasoning_capabilities_dict = model_reasoning_capabilities_instance.to_dict()
# create an instance of ModelReasoningCapabilities from a dict
model_reasoning_capabilities_from_dict = ModelReasoningCapabilities.from_dict(model_reasoning_capabilities_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


