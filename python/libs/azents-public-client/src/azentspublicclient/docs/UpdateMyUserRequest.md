# UpdateMyUserRequest

Current user update request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**locale** | **str** | Account locale (BCP 47) | 

## Example

```python
from azentspublicclient.models.update_my_user_request import UpdateMyUserRequest

# TODO update the JSON string below
json = "{}"
# create an instance of UpdateMyUserRequest from a JSON string
update_my_user_request_instance = UpdateMyUserRequest.from_json(json)
# print the JSON string representation of the object
print(UpdateMyUserRequest.to_json())

# convert the object into a dict
update_my_user_request_dict = update_my_user_request_instance.to_dict()
# create an instance of UpdateMyUserRequest from a dict
update_my_user_request_from_dict = UpdateMyUserRequest.from_dict(update_my_user_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


