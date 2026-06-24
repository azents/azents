# CreatePasswordResetTokenRequest

Password reset token creation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**user_id** | **str** |  | [optional]
**email** | **str** |  | [optional]

## Example

```python
from azentsadminclient.models.create_password_reset_token_request import CreatePasswordResetTokenRequest

# TODO update the JSON string below
json = "{}"
# create an instance of CreatePasswordResetTokenRequest from a JSON string
create_password_reset_token_request_instance = CreatePasswordResetTokenRequest.from_json(json)
# print the JSON string representation of the object
print(CreatePasswordResetTokenRequest.to_json())

# convert the object into a dict
create_password_reset_token_request_dict = create_password_reset_token_request_instance.to_dict()
# create an instance of CreatePasswordResetTokenRequest from a dict
create_password_reset_token_request_from_dict = CreatePasswordResetTokenRequest.from_dict(create_password_reset_token_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
