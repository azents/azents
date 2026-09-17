# WorkspaceUploadCancelRequest

Cancellation request for one exact upload revision.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** | Exact upload revision observed by the caller | 
**current_delivery_number** | **int** |  | [optional] 

## Example

```python
from azentspublicclient.models.workspace_upload_cancel_request import WorkspaceUploadCancelRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUploadCancelRequest from a JSON string
workspace_upload_cancel_request_instance = WorkspaceUploadCancelRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUploadCancelRequest.to_json())

# convert the object into a dict
workspace_upload_cancel_request_dict = workspace_upload_cancel_request_instance.to_dict()
# create an instance of WorkspaceUploadCancelRequest from a dict
workspace_upload_cancel_request_from_dict = WorkspaceUploadCancelRequest.from_dict(workspace_upload_cancel_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


