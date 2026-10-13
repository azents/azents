# RuntimeEnvironmentEntryEdit

One desired entry with an explicit retain or replacement operation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | 
**value** | [**Value**](Value.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_environment_entry_edit import RuntimeEnvironmentEntryEdit

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeEnvironmentEntryEdit from a JSON string
runtime_environment_entry_edit_instance = RuntimeEnvironmentEntryEdit.from_json(json)
# print the JSON string representation of the object
print(RuntimeEnvironmentEntryEdit.to_json())

# convert the object into a dict
runtime_environment_entry_edit_dict = runtime_environment_entry_edit_instance.to_dict()
# create an instance of RuntimeEnvironmentEntryEdit from a dict
runtime_environment_entry_edit_from_dict = RuntimeEnvironmentEntryEdit.from_dict(runtime_environment_entry_edit_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


