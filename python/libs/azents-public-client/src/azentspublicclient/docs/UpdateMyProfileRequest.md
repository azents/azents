# UpdateMyProfileRequest

Own workspace profile update request schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.update_my_profile_request import UpdateMyProfileRequest

# TODO update the JSON string below
json = "{}"
# create an instance of UpdateMyProfileRequest from a JSON string
update_my_profile_request_instance = UpdateMyProfileRequest.from_json(json)
# print the JSON string representation of the object
print(UpdateMyProfileRequest.to_json())

# convert the object into a dict
update_my_profile_request_dict = update_my_profile_request_instance.to_dict()
# create an instance of UpdateMyProfileRequest from a dict
update_my_profile_request_from_dict = UpdateMyProfileRequest.from_dict(update_my_profile_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


