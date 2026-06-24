# CreateSignupTokenResponse

Signup token creation response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**token** | [**SignupTokenResponse**](SignupTokenResponse.md) | Signup token metadata |
**plaintext_token** | **str** | Plaintext signup token |

## Example

```python
from azentsadminclient.models.create_signup_token_response import CreateSignupTokenResponse

# TODO update the JSON string below
json = "{}"
# create an instance of CreateSignupTokenResponse from a JSON string
create_signup_token_response_instance = CreateSignupTokenResponse.from_json(json)
# print the JSON string representation of the object
print(CreateSignupTokenResponse.to_json())

# convert the object into a dict
create_signup_token_response_dict = create_signup_token_response_instance.to_dict()
# create an instance of CreateSignupTokenResponse from a dict
create_signup_token_response_from_dict = CreateSignupTokenResponse.from_dict(create_signup_token_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
