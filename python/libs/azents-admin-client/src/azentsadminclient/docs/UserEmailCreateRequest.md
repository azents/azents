# UserEmailCreateRequest

UserEmail creation request schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**email** | **str** | Email address |

## Example

```python
from azentsadminclient.models.user_email_create_request import UserEmailCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of UserEmailCreateRequest from a JSON string
user_email_create_request_instance = UserEmailCreateRequest.from_json(json)
# print the JSON string representation of the object
print(UserEmailCreateRequest.to_json())

# convert the object into a dict
user_email_create_request_dict = user_email_create_request_instance.to_dict()
# create an instance of UserEmailCreateRequest from a dict
user_email_create_request_from_dict = UserEmailCreateRequest.from_dict(user_email_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
