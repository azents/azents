# SignupTokenResponse

Signup token metadata response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Signup token ID | 
**email** | **str** | Email fixed to token | 
**created_by_user_id** | **str** |  | 
**delivery_method** | [**SignupTokenDeliveryMethod**](SignupTokenDeliveryMethod.md) | Token delivery method | 
**expires_at** | **datetime** | Expiration time | 
**max_uses** | **int** | Maximum use count | 
**used_count** | **int** | Use count | 
**revoked_at** | **datetime** |  | 
**created_at** | **datetime** | Created time | 
**updated_at** | **datetime** | Updated time | 

## Example

```python
from azentsadminclient.models.signup_token_response import SignupTokenResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SignupTokenResponse from a JSON string
signup_token_response_instance = SignupTokenResponse.from_json(json)
# print the JSON string representation of the object
print(SignupTokenResponse.to_json())

# convert the object into a dict
signup_token_response_dict = signup_token_response_instance.to_dict()
# create an instance of SignupTokenResponse from a dict
signup_token_response_from_dict = SignupTokenResponse.from_dict(signup_token_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


