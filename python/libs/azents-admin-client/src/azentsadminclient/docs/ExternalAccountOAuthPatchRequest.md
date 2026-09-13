# ExternalAccountOAuthPatchRequest

Optimistic provider OAuth System Settings patch.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**client_id** | **str** |  | [optional] 
**application_id** | **str** |  | [optional] 
**client_secret** | [**ExternalAccountOAuthSecretActionRequest**](ExternalAccountOAuthSecretActionRequest.md) |  | [optional] 

## Example

```python
from azentsadminclient.models.external_account_o_auth_patch_request import ExternalAccountOAuthPatchRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalAccountOAuthPatchRequest from a JSON string
external_account_o_auth_patch_request_instance = ExternalAccountOAuthPatchRequest.from_json(json)
# print the JSON string representation of the object
print(ExternalAccountOAuthPatchRequest.to_json())

# convert the object into a dict
external_account_o_auth_patch_request_dict = external_account_o_auth_patch_request_instance.to_dict()
# create an instance of ExternalAccountOAuthPatchRequest from a dict
external_account_o_auth_patch_request_from_dict = ExternalAccountOAuthPatchRequest.from_dict(external_account_o_auth_patch_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


