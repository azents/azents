# ModelBuiltInToolCapabilities

Represents provider built-in tool capability.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**supported** | **List[str]** |  | [optional]

## Example

```python
from azentspublicclient.models.model_built_in_tool_capabilities import ModelBuiltInToolCapabilities

# TODO update the JSON string below
json = "{}"
# create an instance of ModelBuiltInToolCapabilities from a JSON string
model_built_in_tool_capabilities_instance = ModelBuiltInToolCapabilities.from_json(json)
# print the JSON string representation of the object
print(ModelBuiltInToolCapabilities.to_json())

# convert the object into a dict
model_built_in_tool_capabilities_dict = model_built_in_tool_capabilities_instance.to_dict()
# create an instance of ModelBuiltInToolCapabilities from a dict
model_built_in_tool_capabilities_from_dict = ModelBuiltInToolCapabilities.from_dict(model_built_in_tool_capabilities_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


