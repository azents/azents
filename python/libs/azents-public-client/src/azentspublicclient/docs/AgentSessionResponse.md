# AgentSessionResponse

Conversation session response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Session ID | 
**agent_id** | **str** | Agent ID | 
**created_at** | **datetime** | Created time | 
**updated_at** | **datetime** | Updated time | 

## Example

```python
from azentspublicclient.models.agent_session_response import AgentSessionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionResponse from a JSON string
agent_session_response_instance = AgentSessionResponse.from_json(json)
# print the JSON string representation of the object
print(AgentSessionResponse.to_json())

# convert the object into a dict
agent_session_response_dict = agent_session_response_instance.to_dict()
# create an instance of AgentSessionResponse from a dict
agent_session_response_from_dict = AgentSessionResponse.from_dict(agent_session_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


