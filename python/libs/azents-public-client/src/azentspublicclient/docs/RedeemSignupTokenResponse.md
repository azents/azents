# RedeemSignupTokenResponse

Signup token redeem response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**access_token** | **str** | JWT access token |
**refresh_token** | **str** | Refresh token |
**expires_in** | **int** | Access token expiration time (seconds) |

## Example

```python
from azentspublicclient.models.redeem_signup_token_response import RedeemSignupTokenResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RedeemSignupTokenResponse from a JSON string
redeem_signup_token_response_instance = RedeemSignupTokenResponse.from_json(json)
# print the JSON string representation of the object
print(RedeemSignupTokenResponse.to_json())

# convert the object into a dict
redeem_signup_token_response_dict = redeem_signup_token_response_instance.to_dict()
# create an instance of RedeemSignupTokenResponse from a dict
redeem_signup_token_response_from_dict = RedeemSignupTokenResponse.from_dict(redeem_signup_token_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


