# LoginMethodsResponse

Login method lookup response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**has_password** | **bool** | Whether password is set |
**email_available** | **bool** | Whether email OTP login is available |

## Example

```python
from azentspublicclient.models.login_methods_response import LoginMethodsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of LoginMethodsResponse from a JSON string
login_methods_response_instance = LoginMethodsResponse.from_json(json)
# print the JSON string representation of the object
print(LoginMethodsResponse.to_json())

# convert the object into a dict
login_methods_response_dict = login_methods_response_instance.to_dict()
# create an instance of LoginMethodsResponse from a dict
login_methods_response_from_dict = LoginMethodsResponse.from_dict(login_methods_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
