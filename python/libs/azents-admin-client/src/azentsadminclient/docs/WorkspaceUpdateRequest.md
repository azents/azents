# WorkspaceUpdateRequest

Workspace update request schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | [optional] 
**handle** | **str** |  | [optional] 

## Example

```python
from azentsadminclient.models.workspace_update_request import WorkspaceUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUpdateRequest from a JSON string
workspace_update_request_instance = WorkspaceUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUpdateRequest.to_json())

# convert the object into a dict
workspace_update_request_dict = workspace_update_request_instance.to_dict()
# create an instance of WorkspaceUpdateRequest from a dict
workspace_update_request_from_dict = WorkspaceUpdateRequest.from_dict(workspace_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


