# ChatLiveRunStateResponse

Current live run state response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**run_id** | **str** | AgentRun ID | 
**phase** | [**AgentRunPhase**](AgentRunPhase.md) | Current run phase | 
**status** | [**AgentRunStatus**](AgentRunStatus.md) | Current run status | 
**inference_profile** | [**AppliedInferenceProfile**](AppliedInferenceProfile.md) | Inference settings applied to the active turn | 
**retry** | [**ChatLiveRunRetryStateResponse**](ChatLiveRunRetryStateResponse.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.chat_live_run_state_response import ChatLiveRunStateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatLiveRunStateResponse from a JSON string
chat_live_run_state_response_instance = ChatLiveRunStateResponse.from_json(json)
# print the JSON string representation of the object
print(ChatLiveRunStateResponse.to_json())

# convert the object into a dict
chat_live_run_state_response_dict = chat_live_run_state_response_instance.to_dict()
# create an instance of ChatLiveRunStateResponse from a dict
chat_live_run_state_response_from_dict = ChatLiveRunStateResponse.from_dict(chat_live_run_state_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


