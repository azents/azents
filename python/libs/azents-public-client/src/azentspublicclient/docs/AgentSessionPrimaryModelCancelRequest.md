# AgentSessionPrimaryModelCancelRequest

Cancel one exact Session reservation generation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**reservation_generation** | **int** |  | 

## Example

```python
from azentspublicclient.models.agent_session_primary_model_cancel_request import AgentSessionPrimaryModelCancelRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionPrimaryModelCancelRequest from a JSON string
agent_session_primary_model_cancel_request_instance = AgentSessionPrimaryModelCancelRequest.from_json(json)
# print the JSON string representation of the object
print(AgentSessionPrimaryModelCancelRequest.to_json())

# convert the object into a dict
agent_session_primary_model_cancel_request_dict = agent_session_primary_model_cancel_request_instance.to_dict()
# create an instance of AgentSessionPrimaryModelCancelRequest from a dict
agent_session_primary_model_cancel_request_from_dict = AgentSessionPrimaryModelCancelRequest.from_dict(agent_session_primary_model_cancel_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


