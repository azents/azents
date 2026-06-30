# ChatGPTOAuthConfig

ChatGPT OAuth display and status settings.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'chatgpt_oauth']
**account_id** | **str** |  | [optional] 
**email** | **str** |  | [optional] 
**plan_type** | **str** |  | [optional] 
**connection_method** | **str** | Connection method | 
**status** | **str** | Connection status | 
**connected_at** | **datetime** |  | [optional] 
**last_refreshed_at** | **datetime** |  | [optional] 
**last_failed_at** | **datetime** |  | [optional] 
**last_failure_reason** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.chat_gpto_auth_config import ChatGPTOAuthConfig

# TODO update the JSON string below
json = "{}"
# create an instance of ChatGPTOAuthConfig from a JSON string
chat_gpto_auth_config_instance = ChatGPTOAuthConfig.from_json(json)
# print the JSON string representation of the object
print(ChatGPTOAuthConfig.to_json())

# convert the object into a dict
chat_gpto_auth_config_dict = chat_gpto_auth_config_instance.to_dict()
# create an instance of ChatGPTOAuthConfig from a dict
chat_gpto_auth_config_from_dict = ChatGPTOAuthConfig.from_dict(chat_gpto_auth_config_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


