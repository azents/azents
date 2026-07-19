# KimiOAuthDeviceStartResponse

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
from azentspublicclient.models.kimi_o_auth_device_start_response import KimiOAuthDeviceStartResponse

# TODO update the JSON string below
json = "{}"
# create an instance of KimiOAuthDeviceStartResponse from a JSON string
kimi_o_auth_device_start_response_instance = KimiOAuthDeviceStartResponse.from_json(json)
# print the JSON string representation of the object
print(KimiOAuthDeviceStartResponse.to_json())

# convert the object into a dict
kimi_o_auth_device_start_response_dict = kimi_o_auth_device_start_response_instance.to_dict()
# create an instance of KimiOAuthDeviceStartResponse from a dict
kimi_o_auth_device_start_response_from_dict = KimiOAuthDeviceStartResponse.from_dict(kimi_o_auth_device_start_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


