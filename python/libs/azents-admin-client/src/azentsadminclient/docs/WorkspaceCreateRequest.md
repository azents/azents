# WorkspaceCreateRequest

Workspace creation request schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Workspace name |
**handle** | **str** | Workspace unique handle |

## Example

```python
from azentsadminclient.models.workspace_create_request import WorkspaceCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceCreateRequest from a JSON string
workspace_create_request_instance = WorkspaceCreateRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceCreateRequest.to_json())

# convert the object into a dict
workspace_create_request_dict = workspace_create_request_instance.to_dict()
# create an instance of WorkspaceCreateRequest from a dict
workspace_create_request_from_dict = WorkspaceCreateRequest.from_dict(workspace_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
