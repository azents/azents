# PreviewSignupTokenRequest

Signup token preview request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**token** | **str** | Signup token | 

## Example

```python
from azentspublicclient.models.preview_signup_token_request import PreviewSignupTokenRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PreviewSignupTokenRequest from a JSON string
preview_signup_token_request_instance = PreviewSignupTokenRequest.from_json(json)
# print the JSON string representation of the object
print(PreviewSignupTokenRequest.to_json())

# convert the object into a dict
preview_signup_token_request_dict = preview_signup_token_request_instance.to_dict()
# create an instance of PreviewSignupTokenRequest from a dict
preview_signup_token_request_from_dict = PreviewSignupTokenRequest.from_dict(preview_signup_token_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


