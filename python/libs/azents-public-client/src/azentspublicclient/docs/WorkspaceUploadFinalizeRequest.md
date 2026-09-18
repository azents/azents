# WorkspaceUploadFinalizeRequest

Finalize request after the browser direct PUT completes.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** | Exact upload revision observed by the caller | 

## Example

```python
from azentspublicclient.models.workspace_upload_finalize_request import WorkspaceUploadFinalizeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUploadFinalizeRequest from a JSON string
workspace_upload_finalize_request_instance = WorkspaceUploadFinalizeRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUploadFinalizeRequest.to_json())

# convert the object into a dict
workspace_upload_finalize_request_dict = workspace_upload_finalize_request_instance.to_dict()
# create an instance of WorkspaceUploadFinalizeRequest from a dict
workspace_upload_finalize_request_from_dict = WorkspaceUploadFinalizeRequest.from_dict(workspace_upload_finalize_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


