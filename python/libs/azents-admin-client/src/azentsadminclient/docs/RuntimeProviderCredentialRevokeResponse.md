# RuntimeProviderCredentialRevokeResponse

Result of revoking one Provider credential.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**revoked** | **bool** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_credential_revoke_response import RuntimeProviderCredentialRevokeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderCredentialRevokeResponse from a JSON string
runtime_provider_credential_revoke_response_instance = RuntimeProviderCredentialRevokeResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderCredentialRevokeResponse.to_json())

# convert the object into a dict
runtime_provider_credential_revoke_response_dict = runtime_provider_credential_revoke_response_instance.to_dict()
# create an instance of RuntimeProviderCredentialRevokeResponse from a dict
runtime_provider_credential_revoke_response_from_dict = RuntimeProviderCredentialRevokeResponse.from_dict(runtime_provider_credential_revoke_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


