# PreviewPasswordResetTokenRequest

Password reset token preview request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**token** | **str** | Password reset token | 

## Example

```python
from azentspublicclient.models.preview_password_reset_token_request import PreviewPasswordResetTokenRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PreviewPasswordResetTokenRequest from a JSON string
preview_password_reset_token_request_instance = PreviewPasswordResetTokenRequest.from_json(json)
# print the JSON string representation of the object
print(PreviewPasswordResetTokenRequest.to_json())

# convert the object into a dict
preview_password_reset_token_request_dict = preview_password_reset_token_request_instance.to_dict()
# create an instance of PreviewPasswordResetTokenRequest from a dict
preview_password_reset_token_request_from_dict = PreviewPasswordResetTokenRequest.from_dict(preview_password_reset_token_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


