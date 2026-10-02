# BuiltinToolSupport

One implemented configurable tool's saved support fact.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**tool** | [**BuiltinToolValue**](BuiltinToolValue.md) |  | 
**support** | [**CapabilitySupport**](CapabilitySupport.md) |  | 

## Example

```python
from azentspublicclient.models.builtin_tool_support import BuiltinToolSupport

# TODO update the JSON string below
json = "{}"
# create an instance of BuiltinToolSupport from a JSON string
builtin_tool_support_instance = BuiltinToolSupport.from_json(json)
# print the JSON string representation of the object
print(BuiltinToolSupport.to_json())

# convert the object into a dict
builtin_tool_support_dict = builtin_tool_support_instance.to_dict()
# create an instance of BuiltinToolSupport from a dict
builtin_tool_support_from_dict = BuiltinToolSupport.from_dict(builtin_tool_support_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


