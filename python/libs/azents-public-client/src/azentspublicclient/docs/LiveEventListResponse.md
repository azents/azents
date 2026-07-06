# LiveEventListResponse

Current live state taxonomy snapshot response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**partial_history** | [**PartialHistoryResponse**](PartialHistoryResponse.md) | Partial history projection list to compose into Chat timeline |
**input_buffers** | [**List[ChatEventResponse]**](ChatEventResponse.md) | Pending input buffer projection list |
**run** | [**ChatLiveRunStateResponse**](ChatLiveRunStateResponse.md) |  | [optional]
**session_run_state** | [**AgentSessionRunState**](AgentSessionRunState.md) | Authoritative run_state for the current session |
**todo** | [**TodoStateResponse**](TodoStateResponse.md) |  | [optional]
**goal** | [**GoalStateResponse**](GoalStateResponse.md) |  | [optional]
**action_executions** | [**List[ActionExecutionProjectionResponse]**](ActionExecutionProjectionResponse.md) | Current action execution projections | [optional]

## Example

```python
from azentspublicclient.models.live_event_list_response import LiveEventListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of LiveEventListResponse from a JSON string
live_event_list_response_instance = LiveEventListResponse.from_json(json)
# print the JSON string representation of the object
print(LiveEventListResponse.to_json())

# convert the object into a dict
live_event_list_response_dict = live_event_list_response_instance.to_dict()
# create an instance of LiveEventListResponse from a dict
live_event_list_response_from_dict = LiveEventListResponse.from_dict(live_event_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


