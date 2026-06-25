# RedeemSignupTokenRequest

Signup token redeem request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**token** | **str** | Signup token | 
**email** | **str** | Signup email | 
**password** | **str** | Initial password | 

## Example

```python
from azentspublicclient.models.redeem_signup_token_request import RedeemSignupTokenRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RedeemSignupTokenRequest from a JSON string
redeem_signup_token_request_instance = RedeemSignupTokenRequest.from_json(json)
# print the JSON string representation of the object
print(RedeemSignupTokenRequest.to_json())

# convert the object into a dict
redeem_signup_token_request_dict = redeem_signup_token_request_instance.to_dict()
# create an instance of RedeemSignupTokenRequest from a dict
redeem_signup_token_request_from_dict = RedeemSignupTokenRequest.from_dict(redeem_signup_token_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


