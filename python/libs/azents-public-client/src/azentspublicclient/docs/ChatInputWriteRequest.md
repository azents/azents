# ChatInputWriteRequest

REST composer input write request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | Agent ID | 
**client_request_id** | **str** | Client-generated idempotency key | 
**message** | **str** | Input message content | 
**action** | [**ChatInputWriteRequestAction**](ChatInputWriteRequestAction.md) |  | [optional] 
**inference_profile** | [**RequestedInferenceProfile**](RequestedInferenceProfile.md) |  | 
**attachments** | **List[str]** |  | [optional] 

## Example

```python
from azentspublicclient.models.chat_input_write_request import ChatInputWriteRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ChatInputWriteRequest from a JSON string
chat_input_write_request_instance = ChatInputWriteRequest.from_json(json)
# print the JSON string representation of the object
print(ChatInputWriteRequest.to_json())

# convert the object into a dict
chat_input_write_request_dict = chat_input_write_request_instance.to_dict()
# create an instance of ChatInputWriteRequest from a dict
chat_input_write_request_from_dict = ChatInputWriteRequest.from_dict(chat_input_write_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


