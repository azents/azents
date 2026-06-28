# AgentSubagentCreateRequest

AgentSubagent creation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**subagent_id** | **str** | Subagent ID to link |
**description** | **str** | Description exposed to the LLM |
**enabled** | **bool** | Enabled state | [optional] [default to True]

## Example

```python
from azentspublicclient.models.agent_subagent_create_request import AgentSubagentCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSubagentCreateRequest from a JSON string
agent_subagent_create_request_instance = AgentSubagentCreateRequest.from_json(json)
# print the JSON string representation of the object
print(AgentSubagentCreateRequest.to_json())

# convert the object into a dict
agent_subagent_create_request_dict = agent_subagent_create_request_instance.to_dict()
# create an instance of AgentSubagentCreateRequest from a dict
agent_subagent_create_request_from_dict = AgentSubagentCreateRequest.from_dict(agent_subagent_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


