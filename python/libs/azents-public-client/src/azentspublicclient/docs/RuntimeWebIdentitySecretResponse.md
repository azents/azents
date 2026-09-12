# RuntimeWebIdentitySecretResponse

Opaque identity secret for a trusted cookie-setting response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**secret** | **str** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_identity_secret_response import RuntimeWebIdentitySecretResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebIdentitySecretResponse from a JSON string
runtime_web_identity_secret_response_instance = RuntimeWebIdentitySecretResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebIdentitySecretResponse.to_json())

# convert the object into a dict
runtime_web_identity_secret_response_dict = runtime_web_identity_secret_response_instance.to_dict()
# create an instance of RuntimeWebIdentitySecretResponse from a dict
runtime_web_identity_secret_response_from_dict = RuntimeWebIdentitySecretResponse.from_dict(runtime_web_identity_secret_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


