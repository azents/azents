# WorkspaceUploadCreateResponse

Upload status and one transient browser PUT ticket.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | [**WorkspaceUploadStatusResponse**](WorkspaceUploadStatusResponse.md) | Upload status | 
**ticket** | [**WorkspaceUploadTicketResponse**](WorkspaceUploadTicketResponse.md) | Direct PUT ticket | 

## Example

```python
from azentspublicclient.models.workspace_upload_create_response import WorkspaceUploadCreateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUploadCreateResponse from a JSON string
workspace_upload_create_response_instance = WorkspaceUploadCreateResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUploadCreateResponse.to_json())

# convert the object into a dict
workspace_upload_create_response_dict = workspace_upload_create_response_instance.to_dict()
# create an instance of WorkspaceUploadCreateResponse from a dict
workspace_upload_create_response_from_dict = WorkspaceUploadCreateResponse.from_dict(workspace_upload_create_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


