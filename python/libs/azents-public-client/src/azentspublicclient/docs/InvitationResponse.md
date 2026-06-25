# InvitationResponse

Invitation response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | WorkspaceInvitation ID (UUID7 hex) | 
**workspace_id** | **str** | Workspace ID | 
**email** | **str** | Invitation target email | 
**role** | [**WorkspaceUserRole**](WorkspaceUserRole.md) | Invitation role | 
**invited_by** | **str** | Inviting WorkspaceUser ID | 
**status** | [**InvitationStatus**](InvitationStatus.md) | Invitation status | 
**created_at** | **datetime** | Created time | 
**updated_at** | **datetime** | Updated time | 

## Example

```python
from azentspublicclient.models.invitation_response import InvitationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of InvitationResponse from a JSON string
invitation_response_instance = InvitationResponse.from_json(json)
# print the JSON string representation of the object
print(InvitationResponse.to_json())

# convert the object into a dict
invitation_response_dict = invitation_response_instance.to_dict()
# create an instance of InvitationResponse from a dict
invitation_response_from_dict = InvitationResponse.from_dict(invitation_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


