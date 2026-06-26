# SendElevationCodeResponse

Elevation OTP send response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**csrf_token** | **str** | CSRF token | 

## Example

```python
from azentspublicclient.models.send_elevation_code_response import SendElevationCodeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SendElevationCodeResponse from a JSON string
send_elevation_code_response_instance = SendElevationCodeResponse.from_json(json)
# print the JSON string representation of the object
print(SendElevationCodeResponse.to_json())

# convert the object into a dict
send_elevation_code_response_dict = send_elevation_code_response_instance.to_dict()
# create an instance of SendElevationCodeResponse from a dict
send_elevation_code_response_from_dict = SendElevationCodeResponse.from_dict(send_elevation_code_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


