# WorkspaceEnvironmentReplace

Complete desired catalog.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**entries** | [**List[WorkspaceEnvironmentEntryEdit]**](WorkspaceEnvironmentEntryEdit.md) |  | 

## Example

```python
from azentspublicclient.models.workspace_environment_replace import WorkspaceEnvironmentReplace

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceEnvironmentReplace from a JSON string
workspace_environment_replace_instance = WorkspaceEnvironmentReplace.from_json(json)
# print the JSON string representation of the object
print(WorkspaceEnvironmentReplace.to_json())

# convert the object into a dict
workspace_environment_replace_dict = workspace_environment_replace_instance.to_dict()
# create an instance of WorkspaceEnvironmentReplace from a dict
workspace_environment_replace_from_dict = WorkspaceEnvironmentReplace.from_dict(workspace_environment_replace_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


