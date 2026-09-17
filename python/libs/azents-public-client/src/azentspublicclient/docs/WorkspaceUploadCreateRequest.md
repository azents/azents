# WorkspaceUploadCreateRequest

Direct Agent Workspace upload admission request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**destination_directory** | **str** | Existing Agent Workspace directory for the destination file | 
**filename** | **str** | Destination basename | 
**expected_size** | **int** | Expected file size in bytes | 
**expected_sha256** | **str** | Lower-case SHA-256 digest of the browser file | 
**media_type** | **str** |  | [optional] 
**session_id** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.workspace_upload_create_request import WorkspaceUploadCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUploadCreateRequest from a JSON string
workspace_upload_create_request_instance = WorkspaceUploadCreateRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUploadCreateRequest.to_json())

# convert the object into a dict
workspace_upload_create_request_dict = workspace_upload_create_request_instance.to_dict()
# create an instance of WorkspaceUploadCreateRequest from a dict
workspace_upload_create_request_from_dict = WorkspaceUploadCreateRequest.from_dict(workspace_upload_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


