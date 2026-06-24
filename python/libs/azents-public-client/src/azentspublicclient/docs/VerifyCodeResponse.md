# VerifyCodeResponse

Authentication code verification response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**access_token** | **str** | JWT access token |
**refresh_token** | **str** | Refresh token |
**expires_in** | **int** | Access token expiration time (seconds) |

## Example

```python
from azentspublicclient.models.verify_code_response import VerifyCodeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of VerifyCodeResponse from a JSON string
verify_code_response_instance = VerifyCodeResponse.from_json(json)
# print the JSON string representation of the object
print(VerifyCodeResponse.to_json())

# convert the object into a dict
verify_code_response_dict = verify_code_response_instance.to_dict()
# create an instance of VerifyCodeResponse from a dict
verify_code_response_from_dict = VerifyCodeResponse.from_dict(verify_code_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
