# KimiOAuthDeviceStatusResponse

Device OAuth status response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session_id** | **str** | OAuth session ID | 
**status** | [**KimiOAuthSessionStatus**](KimiOAuthSessionStatus.md) | Session status | 
**interval_seconds** | **int** | Current provider polling interval | 
**integration** | [**LLMProviderIntegrationResponse**](LLMProviderIntegrationResponse.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.kimi_o_auth_device_status_response import KimiOAuthDeviceStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of KimiOAuthDeviceStatusResponse from a JSON string
kimi_o_auth_device_status_response_instance = KimiOAuthDeviceStatusResponse.from_json(json)
# print the JSON string representation of the object
print(KimiOAuthDeviceStatusResponse.to_json())

# convert the object into a dict
kimi_o_auth_device_status_response_dict = kimi_o_auth_device_status_response_instance.to_dict()
# create an instance of KimiOAuthDeviceStatusResponse from a dict
kimi_o_auth_device_status_response_from_dict = KimiOAuthDeviceStatusResponse.from_dict(kimi_o_auth_device_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


