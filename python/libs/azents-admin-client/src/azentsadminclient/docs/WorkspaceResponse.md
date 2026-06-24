# WorkspaceResponse

Workspace response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Workspace name |
**handle** | **str** | Workspace unique handle |
**created_at** | **datetime** | Created time |
**updated_at** | **datetime** | Updated time |

## Example

```python
from azentsadminclient.models.workspace_response import WorkspaceResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceResponse from a JSON string
workspace_response_instance = WorkspaceResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceResponse.to_json())

# convert the object into a dict
workspace_response_dict = workspace_response_instance.to_dict()
# create an instance of WorkspaceResponse from a dict
workspace_response_from_dict = WorkspaceResponse.from_dict(workspace_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
