# ExternalAccountOAuthSecretActionRequest

Explicit provider OAuth client-secret replacement or clearing action.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**action** | [**SystemSettingSecretActionType**](SystemSettingSecretActionType.md) |  | 
**value** | **str** |  | [optional] 

## Example

```python
from azentsadminclient.models.external_account_o_auth_secret_action_request import ExternalAccountOAuthSecretActionRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalAccountOAuthSecretActionRequest from a JSON string
external_account_o_auth_secret_action_request_instance = ExternalAccountOAuthSecretActionRequest.from_json(json)
# print the JSON string representation of the object
print(ExternalAccountOAuthSecretActionRequest.to_json())

# convert the object into a dict
external_account_o_auth_secret_action_request_dict = external_account_o_auth_secret_action_request_instance.to_dict()
# create an instance of ExternalAccountOAuthSecretActionRequest from a dict
external_account_o_auth_secret_action_request_from_dict = ExternalAccountOAuthSecretActionRequest.from_dict(external_account_o_auth_secret_action_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


