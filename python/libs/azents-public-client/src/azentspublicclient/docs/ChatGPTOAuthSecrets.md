# ChatGPTOAuthSecrets

ChatGPT OAuth token secrets.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'chatgpt_oauth']
**access_token** | **str** | ChatGPT access token |
**refresh_token** | **str** | ChatGPT refresh token |
**id_token** | **str** |  | [optional]
**expires_at** | **datetime** | Access token expiration time |

## Example

```python
from azentspublicclient.models.chat_gpto_auth_secrets import ChatGPTOAuthSecrets

# TODO update the JSON string below
json = "{}"
# create an instance of ChatGPTOAuthSecrets from a JSON string
chat_gpto_auth_secrets_instance = ChatGPTOAuthSecrets.from_json(json)
# print the JSON string representation of the object
print(ChatGPTOAuthSecrets.to_json())

# convert the object into a dict
chat_gpto_auth_secrets_dict = chat_gpto_auth_secrets_instance.to_dict()
# create an instance of ChatGPTOAuthSecrets from a dict
chat_gpto_auth_secrets_from_dict = ChatGPTOAuthSecrets.from_dict(chat_gpto_auth_secrets_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
