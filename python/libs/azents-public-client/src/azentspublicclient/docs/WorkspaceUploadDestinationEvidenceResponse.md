# WorkspaceUploadDestinationEvidenceResponse

Safe destination evidence for an explicit conflict retry.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**kind** | **str** | Observed destination kind | 
**size** | **int** |  | [optional] 
**modified_at** | **datetime** | Observed modification time | 
**conflict_precondition** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.workspace_upload_destination_evidence_response import WorkspaceUploadDestinationEvidenceResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUploadDestinationEvidenceResponse from a JSON string
workspace_upload_destination_evidence_response_instance = WorkspaceUploadDestinationEvidenceResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUploadDestinationEvidenceResponse.to_json())

# convert the object into a dict
workspace_upload_destination_evidence_response_dict = workspace_upload_destination_evidence_response_instance.to_dict()
# create an instance of WorkspaceUploadDestinationEvidenceResponse from a dict
workspace_upload_destination_evidence_response_from_dict = WorkspaceUploadDestinationEvidenceResponse.from_dict(workspace_upload_destination_evidence_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


