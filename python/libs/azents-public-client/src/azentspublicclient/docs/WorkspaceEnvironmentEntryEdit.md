# WorkspaceEnvironmentEntryEdit

Exact stored identity or new entry, preventing name-based stale consent.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | 
**value** | [**Value**](Value.md) |  | 
**id** | **str** |  | 

## Example

```python
from azentspublicclient.models.workspace_environment_entry_edit import WorkspaceEnvironmentEntryEdit

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceEnvironmentEntryEdit from a JSON string
workspace_environment_entry_edit_instance = WorkspaceEnvironmentEntryEdit.from_json(json)
# print the JSON string representation of the object
print(WorkspaceEnvironmentEntryEdit.to_json())

# convert the object into a dict
workspace_environment_entry_edit_dict = workspace_environment_entry_edit_instance.to_dict()
# create an instance of WorkspaceEnvironmentEntryEdit from a dict
workspace_environment_entry_edit_from_dict = WorkspaceEnvironmentEntryEdit.from_dict(workspace_environment_entry_edit_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


