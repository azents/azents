# PreviewPasswordResetTokenResponse

Password reset token preview response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**valid** | **bool** | Usability flag |
**email** | **str** |  |
**expires_at** | **datetime** |  |

## Example

```python
from azentspublicclient.models.preview_password_reset_token_response import PreviewPasswordResetTokenResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PreviewPasswordResetTokenResponse from a JSON string
preview_password_reset_token_response_instance = PreviewPasswordResetTokenResponse.from_json(json)
# print the JSON string representation of the object
print(PreviewPasswordResetTokenResponse.to_json())

# convert the object into a dict
preview_password_reset_token_response_dict = preview_password_reset_token_response_instance.to_dict()
# create an instance of PreviewPasswordResetTokenResponse from a dict
preview_password_reset_token_response_from_dict = PreviewPasswordResetTokenResponse.from_dict(preview_password_reset_token_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


