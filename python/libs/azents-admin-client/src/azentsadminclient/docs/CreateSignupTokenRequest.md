# CreateSignupTokenRequest

Signup token creation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**email** | **str** | Email to pin to the token |
**delivery_method** | [**SignupTokenDeliveryMethod**](SignupTokenDeliveryMethod.md) | Token delivery method |

## Example

```python
from azentsadminclient.models.create_signup_token_request import CreateSignupTokenRequest

# TODO update the JSON string below
json = "{}"
# create an instance of CreateSignupTokenRequest from a JSON string
create_signup_token_request_instance = CreateSignupTokenRequest.from_json(json)
# print the JSON string representation of the object
print(CreateSignupTokenRequest.to_json())

# convert the object into a dict
create_signup_token_request_dict = create_signup_token_request_instance.to_dict()
# create an instance of CreateSignupTokenRequest from a dict
create_signup_token_request_from_dict = CreateSignupTokenRequest.from_dict(create_signup_token_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
