# WorkspaceUploadStatusResponse

Public-safe Workspace upload status projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**identity** | [**WorkspaceUploadIdentityResponse**](WorkspaceUploadIdentityResponse.md) | Requester and Runtime upload identity | 
**revision** | **int** | Monotonic upload revision | 
**destination_directory** | **str** | Normalized destination directory | 
**filename** | **str** | Destination basename | 
**destination_path** | **str** | Normalized destination path | 
**expected_size** | **int** | Expected file size in bytes | 
**received_size** | **int** | Authoritatively received bytes | 
**actual_size** | **int** |  | [optional] 
**sha256** | **str** |  | [optional] 
**media_type** | **str** |  | [optional] 
**phase** | [**WorkspaceUploadPhase**](WorkspaceUploadPhase.md) | Current upload phase | 
**current_delivery_number** | **int** |  | [optional] 
**outcome** | [**WorkspaceUploadOutcome**](WorkspaceUploadOutcome.md) |  | [optional] 
**failure** | [**WorkspaceUploadFailure**](WorkspaceUploadFailure.md) |  | [optional] 
**retry_available** | **bool** | Whether Runtime delivery retry is valid | 
**cancel_available** | **bool** | Whether cancellation is valid | 
**overwrite_available** | **bool** | Whether explicit overwrite retry is valid | 
**destination_evidence** | [**WorkspaceUploadDestinationEvidenceResponse**](WorkspaceUploadDestinationEvidenceResponse.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.workspace_upload_status_response import WorkspaceUploadStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUploadStatusResponse from a JSON string
workspace_upload_status_response_instance = WorkspaceUploadStatusResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUploadStatusResponse.to_json())

# convert the object into a dict
workspace_upload_status_response_dict = workspace_upload_status_response_instance.to_dict()
# create an instance of WorkspaceUploadStatusResponse from a dict
workspace_upload_status_response_from_dict = WorkspaceUploadStatusResponse.from_dict(workspace_upload_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


