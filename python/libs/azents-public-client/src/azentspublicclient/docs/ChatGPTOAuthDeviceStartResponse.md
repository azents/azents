# ChatGPTOAuthDeviceStartResponse

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
from azentspublicclient.models.chat_gpto_auth_device_start_response import ChatGPTOAuthDeviceStartResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatGPTOAuthDeviceStartResponse from a JSON string
chat_gpto_auth_device_start_response_instance = ChatGPTOAuthDeviceStartResponse.from_json(json)
# print the JSON string representation of the object
print(ChatGPTOAuthDeviceStartResponse.to_json())

# convert the object into a dict
chat_gpto_auth_device_start_response_dict = chat_gpto_auth_device_start_response_instance.to_dict()
# create an instance of ChatGPTOAuthDeviceStartResponse from a dict
chat_gpto_auth_device_start_response_from_dict = ChatGPTOAuthDeviceStartResponse.from_dict(chat_gpto_auth_device_start_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
