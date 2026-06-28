# ReceivedInvitationResponse

Received invitation response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Invitation ID |
**workspace_id** | **str** | Workspace ID |
**workspace_name** | **str** | Workspace name |
**workspace_handle** | **str** | Workspace handle |
**email** | **str** | Invitation target email |
**role** | [**WorkspaceUserRole**](WorkspaceUserRole.md) | Invitation role |
**status** | [**InvitationStatus**](InvitationStatus.md) | Invitation status |
**created_at** | **datetime** | Created time |

## Example

```python
from azentspublicclient.models.received_invitation_response import ReceivedInvitationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ReceivedInvitationResponse from a JSON string
received_invitation_response_instance = ReceivedInvitationResponse.from_json(json)
# print the JSON string representation of the object
print(ReceivedInvitationResponse.to_json())

# convert the object into a dict
received_invitation_response_dict = received_invitation_response_instance.to_dict()
# create an instance of ReceivedInvitationResponse from a dict
received_invitation_response_from_dict = ReceivedInvitationResponse.from_dict(received_invitation_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


