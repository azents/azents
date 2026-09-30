# ChatUploadPrepareRequest

Metadata-only manifest for one direct Chat attachment upload.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**filename** | **str** |  | 
**media_type** | **str** |  | 
**size** | **int** |  | 
**sha256** | **str** |  | 

## Example

```python
from azentspublicclient.models.chat_upload_prepare_request import ChatUploadPrepareRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ChatUploadPrepareRequest from a JSON string
chat_upload_prepare_request_instance = ChatUploadPrepareRequest.from_json(json)
# print the JSON string representation of the object
print(ChatUploadPrepareRequest.to_json())

# convert the object into a dict
chat_upload_prepare_request_dict = chat_upload_prepare_request_instance.to_dict()
# create an instance of ChatUploadPrepareRequest from a dict
chat_upload_prepare_request_from_dict = ChatUploadPrepareRequest.from_dict(chat_upload_prepare_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


