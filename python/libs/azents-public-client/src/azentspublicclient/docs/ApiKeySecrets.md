# ApiKeySecrets

API key based secrets for OpenAI, Anthropic, and Google Gemini.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'api_key']
**api_key** | **str** | API key |

## Example

```python
from azentspublicclient.models.api_key_secrets import ApiKeySecrets

# TODO update the JSON string below
json = "{}"
# create an instance of ApiKeySecrets from a JSON string
api_key_secrets_instance = ApiKeySecrets.from_json(json)
# print the JSON string representation of the object
print(ApiKeySecrets.to_json())

# convert the object into a dict
api_key_secrets_dict = api_key_secrets_instance.to_dict()
# create an instance of ApiKeySecrets from a dict
api_key_secrets_from_dict = ApiKeySecrets.from_dict(api_key_secrets_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


