# InvitationListResponse

Invitation list response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[InvitationResponse]**](InvitationResponse.md) | Invitation list | 

## Example

```python
from azentspublicclient.models.invitation_list_response import InvitationListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of InvitationListResponse from a JSON string
invitation_list_response_instance = InvitationListResponse.from_json(json)
# print the JSON string representation of the object
print(InvitationListResponse.to_json())

# convert the object into a dict
invitation_list_response_dict = invitation_list_response_instance.to_dict()
# create an instance of InvitationListResponse from a dict
invitation_list_response_from_dict = InvitationListResponse.from_dict(invitation_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


