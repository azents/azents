# AgentSubagentResponse

AgentSubagent link response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  |
**agent_id** | **str** |  |
**subagent_id** | **str** |  |
**description** | **str** |  |
**enabled** | **bool** |  |
**created_at** | **datetime** |  |
**updated_at** | **datetime** |  |

## Example

```python
from azentspublicclient.models.agent_subagent_response import AgentSubagentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSubagentResponse from a JSON string
agent_subagent_response_instance = AgentSubagentResponse.from_json(json)
# print the JSON string representation of the object
print(AgentSubagentResponse.to_json())

# convert the object into a dict
agent_subagent_response_dict = agent_subagent_response_instance.to_dict()
# create an instance of AgentSubagentResponse from a dict
agent_subagent_response_from_dict = AgentSubagentResponse.from_dict(agent_subagent_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


