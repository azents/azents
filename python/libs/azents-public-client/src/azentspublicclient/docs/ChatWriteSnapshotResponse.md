# ChatWriteSnapshotResponse

Authoritative live snapshot after REST write.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**partial_history_events** | [**List[ChatEventResponse]**](ChatEventResponse.md) | Partial history projection list to compose into Chat timeline |
**input_buffer_events** | [**List[ChatEventResponse]**](ChatEventResponse.md) | Pending input buffer projection list |
**run** | [**ChatLiveRunStateResponse**](ChatLiveRunStateResponse.md) |  | [optional]
**session_run_state** | [**AgentSessionRunState**](AgentSessionRunState.md) | Authoritative run_state for the current session |
**todo** | [**TodoStateResponse**](TodoStateResponse.md) |  | [optional]
**goal** | [**GoalStateResponse**](GoalStateResponse.md) |  | [optional]

## Example

```python
from azentspublicclient.models.chat_write_snapshot_response import ChatWriteSnapshotResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatWriteSnapshotResponse from a JSON string
chat_write_snapshot_response_instance = ChatWriteSnapshotResponse.from_json(json)
# print the JSON string representation of the object
print(ChatWriteSnapshotResponse.to_json())

# convert the object into a dict
chat_write_snapshot_response_dict = chat_write_snapshot_response_instance.to_dict()
# create an instance of ChatWriteSnapshotResponse from a dict
chat_write_snapshot_response_from_dict = ChatWriteSnapshotResponse.from_dict(chat_write_snapshot_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


