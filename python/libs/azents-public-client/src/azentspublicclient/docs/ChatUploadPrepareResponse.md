# ChatUploadPrepareResponse

Transient exact-object PUT ticket; never an attachment publication.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**upload_id** | **str** |  | 
**put_url** | **str** |  | 
**put_headers** | **Dict[str, str]** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.chat_upload_prepare_response import ChatUploadPrepareResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatUploadPrepareResponse from a JSON string
chat_upload_prepare_response_instance = ChatUploadPrepareResponse.from_json(json)
# print the JSON string representation of the object
print(ChatUploadPrepareResponse.to_json())

# convert the object into a dict
chat_upload_prepare_response_dict = chat_upload_prepare_response_instance.to_dict()
# create an instance of ChatUploadPrepareResponse from a dict
chat_upload_prepare_response_from_dict = ChatUploadPrepareResponse.from_dict(chat_upload_prepare_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


