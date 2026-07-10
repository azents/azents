# ChatEventResponse

Event chat event response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Event ID | 
**session_id** | **str** | AgentSession ID | 
**kind** | [**EventKind**](EventKind.md) | Event kind | 
**payload** | **Dict[str, object]** | Event payload | 
**model_order** | **int** | Model input logical order | 
**external_id** | **str** |  | [optional] 
**adapter** | **str** |  | [optional] 
**provider** | **str** |  | [optional] 
**model** | **str** |  | [optional] 
**native_format** | **str** |  | [optional] 
**schema_version** | **str** | Event schema version | 
**created_at** | **datetime** | Created at | 
**inference_run_summary** | [**InferenceRunSummary**](InferenceRunSummary.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.chat_event_response import ChatEventResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatEventResponse from a JSON string
chat_event_response_instance = ChatEventResponse.from_json(json)
# print the JSON string representation of the object
print(ChatEventResponse.to_json())

# convert the object into a dict
chat_event_response_dict = chat_event_response_instance.to_dict()
# create an instance of ChatEventResponse from a dict
chat_event_response_from_dict = ChatEventResponse.from_dict(chat_event_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


