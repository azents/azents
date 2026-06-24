# UserEmailListResponse

UserEmail list response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[UserEmailResponse]**](UserEmailResponse.md) | UserEmail list |
**total** | **int** | Total record count |

## Example

```python
from azentsadminclient.models.user_email_list_response import UserEmailListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of UserEmailListResponse from a JSON string
user_email_list_response_instance = UserEmailListResponse.from_json(json)
# print the JSON string representation of the object
print(UserEmailListResponse.to_json())

# convert the object into a dict
user_email_list_response_dict = user_email_list_response_instance.to_dict()
# create an instance of UserEmailListResponse from a dict
user_email_list_response_from_dict = UserEmailListResponse.from_dict(user_email_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
