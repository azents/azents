# Secrets1

Secrets before encryption

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'api_key']
**api_key** | **str** | API key | 
**secret_access_key** | **str** | AWS Secret Access Key | 
**service_account_json** | **str** | Service account JSON | 
**access_token** | **str** | xAI access token | 
**refresh_token** | **str** | xAI refresh token | 
**id_token** | **str** |  | [optional] 
**expires_at** | **datetime** | Access token expiration time | 

## Example

```python
from azentspublicclient.models.secrets1 import Secrets1

# TODO update the JSON string below
json = "{}"
# create an instance of Secrets1 from a JSON string
secrets1_instance = Secrets1.from_json(json)
# print the JSON string representation of the object
print(Secrets1.to_json())

# convert the object into a dict
secrets1_dict = secrets1_instance.to_dict()
# create an instance of Secrets1 from a dict
secrets1_from_dict = Secrets1.from_dict(secrets1_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


