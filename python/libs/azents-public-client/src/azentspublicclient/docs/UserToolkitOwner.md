# UserToolkitOwner

A User-global connection without an owning Workspace.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**kind** | **str** |  | 
**user_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.user_toolkit_owner import UserToolkitOwner

# TODO update the JSON string below
json = "{}"
# create an instance of UserToolkitOwner from a JSON string
user_toolkit_owner_instance = UserToolkitOwner.from_json(json)
# print the JSON string representation of the object
print(UserToolkitOwner.to_json())

# convert the object into a dict
user_toolkit_owner_dict = user_toolkit_owner_instance.to_dict()
# create an instance of UserToolkitOwner from a dict
user_toolkit_owner_from_dict = UserToolkitOwner.from_dict(user_toolkit_owner_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


