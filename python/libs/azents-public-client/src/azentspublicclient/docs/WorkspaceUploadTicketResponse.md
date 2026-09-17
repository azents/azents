# WorkspaceUploadTicketResponse

Short-lived direct browser PUT capability.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**method** | **str** | Signed HTTP method | 
**url** | **str** | Short-lived presigned PUT URL | 
**expires_at** | **datetime** | Ticket expiration time | 
**headers** | **Dict[str, str]** | Required signed request headers | 

## Example

```python
from azentspublicclient.models.workspace_upload_ticket_response import WorkspaceUploadTicketResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUploadTicketResponse from a JSON string
workspace_upload_ticket_response_instance = WorkspaceUploadTicketResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUploadTicketResponse.to_json())

# convert the object into a dict
workspace_upload_ticket_response_dict = workspace_upload_ticket_response_instance.to_dict()
# create an instance of WorkspaceUploadTicketResponse from a dict
workspace_upload_ticket_response_from_dict = WorkspaceUploadTicketResponse.from_dict(workspace_upload_ticket_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


