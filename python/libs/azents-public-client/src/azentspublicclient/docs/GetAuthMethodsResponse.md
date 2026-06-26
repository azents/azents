# GetAuthMethodsResponse

Authentication method lookup response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**methods** | [**List[AuthMethod]**](AuthMethod.md) | Auth method list | 

## Example

```python
from azentspublicclient.models.get_auth_methods_response import GetAuthMethodsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GetAuthMethodsResponse from a JSON string
get_auth_methods_response_instance = GetAuthMethodsResponse.from_json(json)
# print the JSON string representation of the object
print(GetAuthMethodsResponse.to_json())

# convert the object into a dict
get_auth_methods_response_dict = get_auth_methods_response_instance.to_dict()
# create an instance of GetAuthMethodsResponse from a dict
get_auth_methods_response_from_dict = GetAuthMethodsResponse.from_dict(get_auth_methods_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


