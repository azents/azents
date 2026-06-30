# PasswordLoginResponse

Password login response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**access_token** | **str** | JWT access token | 
**refresh_token** | **str** | Refresh token | 
**expires_in** | **int** | Access token expiration time (seconds) | 

## Example

```python
from azentspublicclient.models.password_login_response import PasswordLoginResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PasswordLoginResponse from a JSON string
password_login_response_instance = PasswordLoginResponse.from_json(json)
# print the JSON string representation of the object
print(PasswordLoginResponse.to_json())

# convert the object into a dict
password_login_response_dict = password_login_response_instance.to_dict()
# create an instance of PasswordLoginResponse from a dict
password_login_response_from_dict = PasswordLoginResponse.from_dict(password_login_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


