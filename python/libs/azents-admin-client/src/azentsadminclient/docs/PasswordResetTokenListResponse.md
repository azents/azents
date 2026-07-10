# PasswordResetTokenListResponse

Password reset token list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[PasswordResetTokenResponse]**](PasswordResetTokenResponse.md) | Password reset token list | 
**total** | **int** | Total record count | 

## Example

```python
from azentsadminclient.models.password_reset_token_list_response import PasswordResetTokenListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PasswordResetTokenListResponse from a JSON string
password_reset_token_list_response_instance = PasswordResetTokenListResponse.from_json(json)
# print the JSON string representation of the object
print(PasswordResetTokenListResponse.to_json())

# convert the object into a dict
password_reset_token_list_response_dict = password_reset_token_list_response_instance.to_dict()
# create an instance of PasswordResetTokenListResponse from a dict
password_reset_token_list_response_from_dict = PasswordResetTokenListResponse.from_dict(password_reset_token_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


