# OAuthAuthorizeRequest

OAuth authorization request for temporary form data storage.  When credentials/config are provided, stores them in the DB before starting auth flow. Used to run OAuth tests with unsaved form values.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**credentials** | **Dict[str, object]** |  | [optional]
**config** | **Dict[str, object]** |  | [optional]

## Example

```python
from azentspublicclient.models.o_auth_authorize_request import OAuthAuthorizeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of OAuthAuthorizeRequest from a JSON string
o_auth_authorize_request_instance = OAuthAuthorizeRequest.from_json(json)
# print the JSON string representation of the object
print(OAuthAuthorizeRequest.to_json())

# convert the object into a dict
o_auth_authorize_request_dict = o_auth_authorize_request_instance.to_dict()
# create an instance of OAuthAuthorizeRequest from a dict
o_auth_authorize_request_from_dict = OAuthAuthorizeRequest.from_dict(o_auth_authorize_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
