# AvatarUploadRequest

Avatar upload ticket issue request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**content_type** | **str** | MIME of the file to upload. JPEG/PNG/WebP allowed | 
**content_length** | **int** | Byte size of the file to upload, up to 5MB | 

## Example

```python
from azentspublicclient.models.avatar_upload_request import AvatarUploadRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AvatarUploadRequest from a JSON string
avatar_upload_request_instance = AvatarUploadRequest.from_json(json)
# print the JSON string representation of the object
print(AvatarUploadRequest.to_json())

# convert the object into a dict
avatar_upload_request_dict = avatar_upload_request_instance.to_dict()
# create an instance of AvatarUploadRequest from a dict
avatar_upload_request_from_dict = AvatarUploadRequest.from_dict(avatar_upload_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


