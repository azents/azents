# ChatLiveRunRecoveryStateResponse

User-safe recoverable stopped Run response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**kind** | **str** | Recovery kind | 
**user_message** | **str** | User-safe stopped Run message | 
**operation** | **str** | Model operation that was stopped | 
**source_run_id** | **str** | Recoverable stopped AgentRun ID | 
**stopped_at** | **str** | Stopped timestamp | 

## Example

```python
from azentspublicclient.models.chat_live_run_recovery_state_response import ChatLiveRunRecoveryStateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatLiveRunRecoveryStateResponse from a JSON string
chat_live_run_recovery_state_response_instance = ChatLiveRunRecoveryStateResponse.from_json(json)
# print the JSON string representation of the object
print(ChatLiveRunRecoveryStateResponse.to_json())

# convert the object into a dict
chat_live_run_recovery_state_response_dict = chat_live_run_recovery_state_response_instance.to_dict()
# create an instance of ChatLiveRunRecoveryStateResponse from a dict
chat_live_run_recovery_state_response_from_dict = ChatLiveRunRecoveryStateResponse.from_dict(chat_live_run_recovery_state_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


