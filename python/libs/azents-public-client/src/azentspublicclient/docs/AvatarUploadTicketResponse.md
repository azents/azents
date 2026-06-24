# AvatarUploadTicketResponse

Presigned PUT ticket response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**upload_key** | **str** | Upload key to pass during finalize |
**upload_url** | **str** | Presigned URL for the client to PUT to |
**expires_at** | **datetime** | URL expiration time, ISO 8601 and tz-aware |

## Example

```python
from azentspublicclient.models.avatar_upload_ticket_response import AvatarUploadTicketResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AvatarUploadTicketResponse from a JSON string
avatar_upload_ticket_response_instance = AvatarUploadTicketResponse.from_json(json)
# print the JSON string representation of the object
print(AvatarUploadTicketResponse.to_json())

# convert the object into a dict
avatar_upload_ticket_response_dict = avatar_upload_ticket_response_instance.to_dict()
# create an instance of AvatarUploadTicketResponse from a dict
avatar_upload_ticket_response_from_dict = AvatarUploadTicketResponse.from_dict(avatar_upload_ticket_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
