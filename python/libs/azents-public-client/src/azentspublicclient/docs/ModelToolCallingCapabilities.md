# ModelToolCallingCapabilities

Final function and function-schema capabilities.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**supported** | **bool** |  | [optional] [default to False]
**parallel_tool_calls** | **bool** |  | [optional] [default to False]
**strict_json_schema** | **bool** |  | [optional] [default to False]

## Example

```python
from azentspublicclient.models.model_tool_calling_capabilities import ModelToolCallingCapabilities

# TODO update the JSON string below
json = "{}"
# create an instance of ModelToolCallingCapabilities from a JSON string
model_tool_calling_capabilities_instance = ModelToolCallingCapabilities.from_json(json)
# print the JSON string representation of the object
print(ModelToolCallingCapabilities.to_json())

# convert the object into a dict
model_tool_calling_capabilities_dict = model_tool_calling_capabilities_instance.to_dict()
# create an instance of ModelToolCallingCapabilities from a dict
model_tool_calling_capabilities_from_dict = ModelToolCallingCapabilities.from_dict(model_tool_calling_capabilities_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


