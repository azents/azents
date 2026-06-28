# AuthMethod

Auth method.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Auth method type (email, password) |
**enabled** | **bool** | Enabled flag |
**configured** | **bool** | Whether user configured credential |
**valid** | **bool** | Whether usable in current environment |
**can_login** | **bool** | Whether usable for login |
**can_elevate** | **bool** | Whether usable for Elevation |
**can_remove** | **bool** | Whether removable |
**unavailable_reason** | **str** |  | [optional]

## Example

```python
from azentspublicclient.models.auth_method import AuthMethod

# TODO update the JSON string below
json = "{}"
# create an instance of AuthMethod from a JSON string
auth_method_instance = AuthMethod.from_json(json)
# print the JSON string representation of the object
print(AuthMethod.to_json())

# convert the object into a dict
auth_method_dict = auth_method_instance.to_dict()
# create an instance of AuthMethod from a dict
auth_method_from_dict = AuthMethod.from_dict(auth_method_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


