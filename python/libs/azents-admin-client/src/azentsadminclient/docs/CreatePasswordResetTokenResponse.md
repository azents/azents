# CreatePasswordResetTokenResponse

Password reset token creation response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**token** | [**PasswordResetTokenResponse**](PasswordResetTokenResponse.md) | Password reset token metadata | 
**plaintext_token** | **str** | Plaintext password reset token | 
**reset_url** | **str** | Password reset URL | 

## Example

```python
from azentsadminclient.models.create_password_reset_token_response import CreatePasswordResetTokenResponse

# TODO update the JSON string below
json = "{}"
# create an instance of CreatePasswordResetTokenResponse from a JSON string
create_password_reset_token_response_instance = CreatePasswordResetTokenResponse.from_json(json)
# print the JSON string representation of the object
print(CreatePasswordResetTokenResponse.to_json())

# convert the object into a dict
create_password_reset_token_response_dict = create_password_reset_token_response_instance.to_dict()
# create an instance of CreatePasswordResetTokenResponse from a dict
create_password_reset_token_response_from_dict = CreatePasswordResetTokenResponse.from_dict(create_password_reset_token_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


