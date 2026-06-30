# RedeemPasswordResetTokenResponse

Password reset token redeem response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**success** | **bool** | Success state | 

## Example

```python
from azentspublicclient.models.redeem_password_reset_token_response import RedeemPasswordResetTokenResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RedeemPasswordResetTokenResponse from a JSON string
redeem_password_reset_token_response_instance = RedeemPasswordResetTokenResponse.from_json(json)
# print the JSON string representation of the object
print(RedeemPasswordResetTokenResponse.to_json())

# convert the object into a dict
redeem_password_reset_token_response_dict = redeem_password_reset_token_response_instance.to_dict()
# create an instance of RedeemPasswordResetTokenResponse from a dict
redeem_password_reset_token_response_from_dict = RedeemPasswordResetTokenResponse.from_dict(redeem_password_reset_token_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


