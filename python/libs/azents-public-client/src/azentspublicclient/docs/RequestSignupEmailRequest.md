# RequestSignupEmailRequest

Signup email request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**email** | **str** | Signup email |

## Example

```python
from azentspublicclient.models.request_signup_email_request import RequestSignupEmailRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RequestSignupEmailRequest from a JSON string
request_signup_email_request_instance = RequestSignupEmailRequest.from_json(json)
# print the JSON string representation of the object
print(RequestSignupEmailRequest.to_json())

# convert the object into a dict
request_signup_email_request_dict = request_signup_email_request_instance.to_dict()
# create an instance of RequestSignupEmailRequest from a dict
request_signup_email_request_from_dict = RequestSignupEmailRequest.from_dict(request_signup_email_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
