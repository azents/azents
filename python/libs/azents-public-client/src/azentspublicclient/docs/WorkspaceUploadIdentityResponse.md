# WorkspaceUploadIdentityResponse

Requester and Runtime identity for one Workspace upload.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**upload_id** | **str** | Workspace upload ID | 
**requester_user_id** | **str** | Authenticated requester User ID | 
**workspace_id** | **str** | Workspace ID | 
**agent_id** | **str** | Agent ID | 
**runtime_id** | **str** | Admitted Agent Runtime ID | 
**desired_generation** | **int** | Admitted Runtime desired generation | 
**session_id** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.workspace_upload_identity_response import WorkspaceUploadIdentityResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUploadIdentityResponse from a JSON string
workspace_upload_identity_response_instance = WorkspaceUploadIdentityResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUploadIdentityResponse.to_json())

# convert the object into a dict
workspace_upload_identity_response_dict = workspace_upload_identity_response_instance.to_dict()
# create an instance of WorkspaceUploadIdentityResponse from a dict
workspace_upload_identity_response_from_dict = WorkspaceUploadIdentityResponse.from_dict(workspace_upload_identity_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


