# ElevateWithEmailRequest

Email OTP elevation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**code** | **str** | 6-digit authentication code | 
**csrf_token** | **str** | CSRF token | 

## Example

```python
from azentspublicclient.models.elevate_with_email_request import ElevateWithEmailRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ElevateWithEmailRequest from a JSON string
elevate_with_email_request_instance = ElevateWithEmailRequest.from_json(json)
# print the JSON string representation of the object
print(ElevateWithEmailRequest.to_json())

# convert the object into a dict
elevate_with_email_request_dict = elevate_with_email_request_instance.to_dict()
# create an instance of ElevateWithEmailRequest from a dict
elevate_with_email_request_from_dict = ElevateWithEmailRequest.from_dict(elevate_with_email_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


