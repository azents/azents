# ReceivedInvitationListResponse

Received invitation list response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ReceivedInvitationResponse]**](ReceivedInvitationResponse.md) | Received invitation list |

## Example

```python
from azentspublicclient.models.received_invitation_list_response import ReceivedInvitationListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ReceivedInvitationListResponse from a JSON string
received_invitation_list_response_instance = ReceivedInvitationListResponse.from_json(json)
# print the JSON string representation of the object
print(ReceivedInvitationListResponse.to_json())

# convert the object into a dict
received_invitation_list_response_dict = received_invitation_list_response_instance.to_dict()
# create an instance of ReceivedInvitationListResponse from a dict
received_invitation_list_response_from_dict = ReceivedInvitationListResponse.from_dict(received_invitation_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


