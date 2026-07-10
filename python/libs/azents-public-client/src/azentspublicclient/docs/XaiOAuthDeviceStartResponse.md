# XaiOAuthDeviceStartResponse

Device OAuth start response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session_id** | **str** | OAuth session ID | 
**user_code** | **str** | Device user code | 
**verification_uri** | **str** | Device verification URI | 
**interval_seconds** | **int** | Provider polling interval | 
**expires_at** | **datetime** | Session expiry | 

## Example

```python
from azentspublicclient.models.xai_o_auth_device_start_response import XaiOAuthDeviceStartResponse

# TODO update the JSON string below
json = "{}"
# create an instance of XaiOAuthDeviceStartResponse from a JSON string
xai_o_auth_device_start_response_instance = XaiOAuthDeviceStartResponse.from_json(json)
# print the JSON string representation of the object
print(XaiOAuthDeviceStartResponse.to_json())

# convert the object into a dict
xai_o_auth_device_start_response_dict = xai_o_auth_device_start_response_instance.to_dict()
# create an instance of XaiOAuthDeviceStartResponse from a dict
xai_o_auth_device_start_response_from_dict = XaiOAuthDeviceStartResponse.from_dict(xai_o_auth_device_start_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


