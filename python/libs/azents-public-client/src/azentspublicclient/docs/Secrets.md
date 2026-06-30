# Secrets

Secrets such as API keys

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'api_key']
**api_key** | **str** | API key | 
**secret_access_key** | **str** | AWS Secret Access Key | 
**service_account_json** | **str** | Service account JSON | 
**access_token** | **str** | ChatGPT access token | 
**refresh_token** | **str** | ChatGPT refresh token | 
**id_token** | **str** |  | [optional] 
**expires_at** | **datetime** | Access token expiration time | 

## Example

```python
from azentspublicclient.models.secrets import Secrets

# TODO update the JSON string below
json = "{}"
# create an instance of Secrets from a JSON string
secrets_instance = Secrets.from_json(json)
# print the JSON string representation of the object
print(Secrets.to_json())

# convert the object into a dict
secrets_dict = secrets_instance.to_dict()
# create an instance of Secrets from a dict
secrets_from_dict = Secrets.from_dict(secrets_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


