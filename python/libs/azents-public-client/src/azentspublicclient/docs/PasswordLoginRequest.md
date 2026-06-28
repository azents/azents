# PasswordLoginRequest

Password login request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**email** | **str** | Email address |
**password** | **str** | Password |

## Example

```python
from azentspublicclient.models.password_login_request import PasswordLoginRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PasswordLoginRequest from a JSON string
password_login_request_instance = PasswordLoginRequest.from_json(json)
# print the JSON string representation of the object
print(PasswordLoginRequest.to_json())

# convert the object into a dict
password_login_request_dict = password_login_request_instance.to_dict()
# create an instance of PasswordLoginRequest from a dict
password_login_request_from_dict = PasswordLoginRequest.from_dict(password_login_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


