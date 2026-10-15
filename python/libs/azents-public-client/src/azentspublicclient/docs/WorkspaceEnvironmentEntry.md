# WorkspaceEnvironmentEntry

Public catalog metadata without a secret value.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**name** | **str** |  | 
**has_value** | **bool** |  | 

## Example

```python
from azentspublicclient.models.workspace_environment_entry import WorkspaceEnvironmentEntry

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceEnvironmentEntry from a JSON string
workspace_environment_entry_instance = WorkspaceEnvironmentEntry.from_json(json)
# print the JSON string representation of the object
print(WorkspaceEnvironmentEntry.to_json())

# convert the object into a dict
workspace_environment_entry_dict = workspace_environment_entry_instance.to_dict()
# create an instance of WorkspaceEnvironmentEntry from a dict
workspace_environment_entry_from_dict = WorkspaceEnvironmentEntry.from_dict(workspace_environment_entry_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


