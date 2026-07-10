# XaiOAuthDeviceStatusResponse

Device OAuth status response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session_id** | **str** | OAuth session ID | 
**status** | [**XaiOAuthSessionStatus**](XaiOAuthSessionStatus.md) | Session status | 
**interval_seconds** | **int** | Current provider polling interval | 
**integration** | [**LLMProviderIntegrationResponse**](LLMProviderIntegrationResponse.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.xai_o_auth_device_status_response import XaiOAuthDeviceStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of XaiOAuthDeviceStatusResponse from a JSON string
xai_o_auth_device_status_response_instance = XaiOAuthDeviceStatusResponse.from_json(json)
# print the JSON string representation of the object
print(XaiOAuthDeviceStatusResponse.to_json())

# convert the object into a dict
xai_o_auth_device_status_response_dict = xai_o_auth_device_status_response_instance.to_dict()
# create an instance of XaiOAuthDeviceStatusResponse from a dict
xai_o_auth_device_status_response_from_dict = XaiOAuthDeviceStatusResponse.from_dict(xai_o_auth_device_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


