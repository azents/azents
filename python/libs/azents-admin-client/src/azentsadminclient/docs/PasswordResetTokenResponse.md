# PasswordResetTokenResponse

Password reset token metadata response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Password reset token ID | 
**user_id** | **str** | Reset target User ID | 
**created_by_user_id** | **str** |  | 
**expires_at** | **datetime** | Expiration time | 
**used_at** | **datetime** |  | 
**revoked_at** | **datetime** |  | 
**created_at** | **datetime** | Created time | 
**updated_at** | **datetime** | Updated time | 

## Example

```python
from azentsadminclient.models.password_reset_token_response import PasswordResetTokenResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PasswordResetTokenResponse from a JSON string
password_reset_token_response_instance = PasswordResetTokenResponse.from_json(json)
# print the JSON string representation of the object
print(PasswordResetTokenResponse.to_json())

# convert the object into a dict
password_reset_token_response_dict = password_reset_token_response_instance.to_dict()
# create an instance of PasswordResetTokenResponse from a dict
password_reset_token_response_from_dict = PasswordResetTokenResponse.from_dict(password_reset_token_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


