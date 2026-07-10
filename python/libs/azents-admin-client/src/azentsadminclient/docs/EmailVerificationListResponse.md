# EmailVerificationListResponse

EmailVerification list response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[EmailVerificationResponse]**](EmailVerificationResponse.md) | Authentication record list | 
**total** | **int** | Total record count | 

## Example

```python
from azentsadminclient.models.email_verification_list_response import EmailVerificationListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of EmailVerificationListResponse from a JSON string
email_verification_list_response_instance = EmailVerificationListResponse.from_json(json)
# print the JSON string representation of the object
print(EmailVerificationListResponse.to_json())

# convert the object into a dict
email_verification_list_response_dict = email_verification_list_response_instance.to_dict()
# create an instance of EmailVerificationListResponse from a dict
email_verification_list_response_from_dict = EmailVerificationListResponse.from_dict(email_verification_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


