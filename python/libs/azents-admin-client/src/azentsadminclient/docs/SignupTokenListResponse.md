# SignupTokenListResponse

Signup token list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[SignupTokenResponse]**](SignupTokenResponse.md) | Signup token list |
**total** | **int** | Total record count |

## Example

```python
from azentsadminclient.models.signup_token_list_response import SignupTokenListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SignupTokenListResponse from a JSON string
signup_token_list_response_instance = SignupTokenListResponse.from_json(json)
# print the JSON string representation of the object
print(SignupTokenListResponse.to_json())

# convert the object into a dict
signup_token_list_response_dict = signup_token_list_response_instance.to_dict()
# create an instance of SignupTokenListResponse from a dict
signup_token_list_response_from_dict = SignupTokenListResponse.from_dict(signup_token_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
