# WorkspaceMode

Workspace mode for the created session

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Workspace mode type |
**project_paths** | **List[str]** | Exact Project paths to register on the created session |
**source_project_path** | **str** | Source Project path |
**starting_ref** | **str** | Starting Git ref |

## Example

```python
from azentspublicclient.models.workspace_mode import WorkspaceMode

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceMode from a JSON string
workspace_mode_instance = WorkspaceMode.from_json(json)
# print the JSON string representation of the object
print(WorkspaceMode.to_json())

# convert the object into a dict
workspace_mode_dict = workspace_mode_instance.to_dict()
# create an instance of WorkspaceMode from a dict
workspace_mode_from_dict = WorkspaceMode.from_dict(workspace_mode_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
