# AvatarFinalizeRequest

Finalize request after upload completion.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**upload_key** | **str** | Upload key from issue-ticket, subject to scope revalidation | 
**filename** | **str** | Original filename, kept in response metadata | 

## Example

```python
from azentspublicclient.models.avatar_finalize_request import AvatarFinalizeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AvatarFinalizeRequest from a JSON string
avatar_finalize_request_instance = AvatarFinalizeRequest.from_json(json)
# print the JSON string representation of the object
print(AvatarFinalizeRequest.to_json())

# convert the object into a dict
avatar_finalize_request_dict = avatar_finalize_request_instance.to_dict()
# create an instance of AvatarFinalizeRequest from a dict
avatar_finalize_request_from_dict = AvatarFinalizeRequest.from_dict(avatar_finalize_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


