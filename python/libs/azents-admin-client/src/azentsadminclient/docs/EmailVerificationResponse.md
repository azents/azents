# EmailVerificationResponse

EmailVerification response schema, including code.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Verification ID (UUID7 hex) |
**email** | **str** | Email address |
**code** | **str** | Six-digit verification code |
**csrf_token** | **str** | CSRF token |
**expires_at** | **datetime** | Expiration time |
**verified_at** | **datetime** |  | [optional]
**created_at** | **datetime** | Created time |

## Example

```python
from azentsadminclient.models.email_verification_response import EmailVerificationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of EmailVerificationResponse from a JSON string
email_verification_response_instance = EmailVerificationResponse.from_json(json)
# print the JSON string representation of the object
print(EmailVerificationResponse.to_json())

# convert the object into a dict
email_verification_response_dict = email_verification_response_instance.to_dict()
# create an instance of EmailVerificationResponse from a dict
email_verification_response_from_dict = EmailVerificationResponse.from_dict(email_verification_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
