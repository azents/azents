# ChatGPTOAuthDeviceStatusResponse

Device OAuth status response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session_id** | **str** | OAuth session ID |
**status** | [**ChatGPTOAuthSessionStatus**](ChatGPTOAuthSessionStatus.md) | Session status |
**integration** | [**LLMProviderIntegrationResponse**](LLMProviderIntegrationResponse.md) |  | [optional]

## Example

```python
from azentspublicclient.models.chat_gpto_auth_device_status_response import ChatGPTOAuthDeviceStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatGPTOAuthDeviceStatusResponse from a JSON string
chat_gpto_auth_device_status_response_instance = ChatGPTOAuthDeviceStatusResponse.from_json(json)
# print the JSON string representation of the object
print(ChatGPTOAuthDeviceStatusResponse.to_json())

# convert the object into a dict
chat_gpto_auth_device_status_response_dict = chat_gpto_auth_device_status_response_instance.to_dict()
# create an instance of ChatGPTOAuthDeviceStatusResponse from a dict
chat_gpto_auth_device_status_response_from_dict = ChatGPTOAuthDeviceStatusResponse.from_dict(chat_gpto_auth_device_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
