# UploadResponse

File upload response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**attachment_id** | **str** | Exchange attachment ID | 
**uri** | **str** | Uploaded file URI | 
**media_type** | **str** | File MIME type | 
**size** | **int** | File size in bytes | 
**name** | **str** | Display filename | 

## Example

```python
from azentspublicclient.models.upload_response import UploadResponse

# TODO update the JSON string below
json = "{}"
# create an instance of UploadResponse from a JSON string
upload_response_instance = UploadResponse.from_json(json)
# print the JSON string representation of the object
print(UploadResponse.to_json())

# convert the object into a dict
upload_response_dict = upload_response_instance.to_dict()
# create an instance of UploadResponse from a dict
upload_response_from_dict = UploadResponse.from_dict(upload_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


