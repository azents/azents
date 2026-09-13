# RuntimeWebIdentityRevokeRequest

Exact identity secret revoked during trusted logout.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**secret** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_identity_revoke_request import RuntimeWebIdentityRevokeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebIdentityRevokeRequest from a JSON string
runtime_web_identity_revoke_request_instance = RuntimeWebIdentityRevokeRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebIdentityRevokeRequest.to_json())

# convert the object into a dict
runtime_web_identity_revoke_request_dict = runtime_web_identity_revoke_request_instance.to_dict()
# create an instance of RuntimeWebIdentityRevokeRequest from a dict
runtime_web_identity_revoke_request_from_dict = RuntimeWebIdentityRevokeRequest.from_dict(runtime_web_identity_revoke_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


