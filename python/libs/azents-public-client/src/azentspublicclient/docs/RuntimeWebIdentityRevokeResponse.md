# RuntimeWebIdentityRevokeResponse

Identity revocation outcome.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**revoked** | **bool** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_identity_revoke_response import RuntimeWebIdentityRevokeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebIdentityRevokeResponse from a JSON string
runtime_web_identity_revoke_response_instance = RuntimeWebIdentityRevokeResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebIdentityRevokeResponse.to_json())

# convert the object into a dict
runtime_web_identity_revoke_response_dict = runtime_web_identity_revoke_response_instance.to_dict()
# create an instance of RuntimeWebIdentityRevokeResponse from a dict
runtime_web_identity_revoke_response_from_dict = RuntimeWebIdentityRevokeResponse.from_dict(runtime_web_identity_revoke_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


