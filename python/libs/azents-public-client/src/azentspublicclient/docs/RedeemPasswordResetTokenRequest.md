# RedeemPasswordResetTokenRequest

Password reset token redeem request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**token** | **str** | Password reset token |
**password** | **str** | New password |

## Example

```python
from azentspublicclient.models.redeem_password_reset_token_request import RedeemPasswordResetTokenRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RedeemPasswordResetTokenRequest from a JSON string
redeem_password_reset_token_request_instance = RedeemPasswordResetTokenRequest.from_json(json)
# print the JSON string representation of the object
print(RedeemPasswordResetTokenRequest.to_json())

# convert the object into a dict
redeem_password_reset_token_request_dict = redeem_password_reset_token_request_instance.to_dict()
# create an instance of RedeemPasswordResetTokenRequest from a dict
redeem_password_reset_token_request_from_dict = RedeemPasswordResetTokenRequest.from_dict(redeem_password_reset_token_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


