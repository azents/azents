# UserEmailResponse

UserEmail response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | UserEmail ID (UUID7 hex) |
**user_id** | **str** | Owning User ID |
**email** | **str** | Email address |
**verified_at** | **datetime** |  | [optional]
**created_at** | **datetime** | Created time |
**updated_at** | **datetime** | Updated time |

## Example

```python
from azentsadminclient.models.user_email_response import UserEmailResponse

# TODO update the JSON string below
json = "{}"
# create an instance of UserEmailResponse from a JSON string
user_email_response_instance = UserEmailResponse.from_json(json)
# print the JSON string representation of the object
print(UserEmailResponse.to_json())

# convert the object into a dict
user_email_response_dict = user_email_response_instance.to_dict()
# create an instance of UserEmailResponse from a dict
user_email_response_from_dict = UserEmailResponse.from_dict(user_email_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
