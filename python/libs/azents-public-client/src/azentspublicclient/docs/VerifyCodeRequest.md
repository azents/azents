# VerifyCodeRequest

Authentication code verification request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**email** | **str** | Email address |
**code** | **str** | 6-digit authentication code |
**csrf_token** | **str** | CSRF token |

## Example

```python
from azentspublicclient.models.verify_code_request import VerifyCodeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of VerifyCodeRequest from a JSON string
verify_code_request_instance = VerifyCodeRequest.from_json(json)
# print the JSON string representation of the object
print(VerifyCodeRequest.to_json())

# convert the object into a dict
verify_code_request_dict = verify_code_request_instance.to_dict()
# create an instance of VerifyCodeRequest from a dict
verify_code_request_from_dict = VerifyCodeRequest.from_dict(verify_code_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
