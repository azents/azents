# BuiltinToolConfig

Built-in tool setting enabled for one selectable model option.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Built-in tool name, for example web_search | 
**config** | **Dict[str, object]** | Per-tool options | [optional] 

## Example

```python
from azentspublicclient.models.builtin_tool_config import BuiltinToolConfig

# TODO update the JSON string below
json = "{}"
# create an instance of BuiltinToolConfig from a JSON string
builtin_tool_config_instance = BuiltinToolConfig.from_json(json)
# print the JSON string representation of the object
print(BuiltinToolConfig.to_json())

# convert the object into a dict
builtin_tool_config_dict = builtin_tool_config_instance.to_dict()
# create an instance of BuiltinToolConfig from a dict
builtin_tool_config_from_dict = BuiltinToolConfig.from_dict(builtin_tool_config_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


