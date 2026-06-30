# SignupStatusResponse

Signup status response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**email_signup_available** | **bool** | Whether email signup link requests are available | 

## Example

```python
from azentspublicclient.models.signup_status_response import SignupStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SignupStatusResponse from a JSON string
signup_status_response_instance = SignupStatusResponse.from_json(json)
# print the JSON string representation of the object
print(SignupStatusResponse.to_json())

# convert the object into a dict
signup_status_response_dict = signup_status_response_instance.to_dict()
# create an instance of SignupStatusResponse from a dict
signup_status_response_from_dict = SignupStatusResponse.from_dict(signup_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


