# XaiOAuthSecrets

xAI OAuth token secrets.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'xai_oauth']
**access_token** | **str** | xAI access token | 
**refresh_token** | **str** | xAI refresh token | 
**id_token** | **str** |  | [optional] 
**expires_at** | **datetime** | Access token expiration time | 

## Example

```python
from azentspublicclient.models.xai_o_auth_secrets import XaiOAuthSecrets

# TODO update the JSON string below
json = "{}"
# create an instance of XaiOAuthSecrets from a JSON string
xai_o_auth_secrets_instance = XaiOAuthSecrets.from_json(json)
# print the JSON string representation of the object
print(XaiOAuthSecrets.to_json())

# convert the object into a dict
xai_o_auth_secrets_dict = xai_o_auth_secrets_instance.to_dict()
# create an instance of XaiOAuthSecrets from a dict
xai_o_auth_secrets_from_dict = XaiOAuthSecrets.from_dict(xai_o_auth_secrets_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


