# ChatEventPageResponse

Event chat event page response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ChatEventResponse]**](ChatEventResponse.md) | Event list | 
**has_more** | **bool** | Whether older events exist | 
**has_newer** | **bool** | Whether newer events exist | [optional] [default to False]
**next_cursor** | **str** |  | [optional] 
**previous_cursor** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.chat_event_page_response import ChatEventPageResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatEventPageResponse from a JSON string
chat_event_page_response_instance = ChatEventPageResponse.from_json(json)
# print the JSON string representation of the object
print(ChatEventPageResponse.to_json())

# convert the object into a dict
chat_event_page_response_dict = chat_event_page_response_instance.to_dict()
# create an instance of ChatEventPageResponse from a dict
chat_event_page_response_from_dict = ChatEventPageResponse.from_dict(chat_event_page_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


