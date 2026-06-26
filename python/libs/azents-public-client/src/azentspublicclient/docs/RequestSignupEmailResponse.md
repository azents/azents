# RequestSignupEmailResponse

Signup email response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**sent** | **bool** | Whether email was sent | 

## Example

```python
from azentspublicclient.models.request_signup_email_response import RequestSignupEmailResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RequestSignupEmailResponse from a JSON string
request_signup_email_response_instance = RequestSignupEmailResponse.from_json(json)
# print the JSON string representation of the object
print(RequestSignupEmailResponse.to_json())

# convert the object into a dict
request_signup_email_response_dict = request_signup_email_response_instance.to_dict()
# create an instance of RequestSignupEmailResponse from a dict
request_signup_email_response_from_dict = RequestSignupEmailResponse.from_dict(request_signup_email_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


