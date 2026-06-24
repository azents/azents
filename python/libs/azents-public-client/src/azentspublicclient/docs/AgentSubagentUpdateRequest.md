# AgentSubagentUpdateRequest

AgentSubagent update request, for partial updates.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**description** | **str** | Description exposed to LLM | [optional]
**enabled** | **bool** | Enabled flag | [optional]

## Example

```python
from azentspublicclient.models.agent_subagent_update_request import AgentSubagentUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSubagentUpdateRequest from a JSON string
agent_subagent_update_request_instance = AgentSubagentUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(AgentSubagentUpdateRequest.to_json())

# convert the object into a dict
agent_subagent_update_request_dict = agent_subagent_update_request_instance.to_dict()
# create an instance of AgentSubagentUpdateRequest from a dict
agent_subagent_update_request_from_dict = AgentSubagentUpdateRequest.from_dict(agent_subagent_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
