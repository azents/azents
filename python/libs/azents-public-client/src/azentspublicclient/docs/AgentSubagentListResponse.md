# AgentSubagentListResponse

AgentSubagent list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[AgentSubagentResponse]**](AgentSubagentResponse.md) |  |

## Example

```python
from azentspublicclient.models.agent_subagent_list_response import AgentSubagentListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSubagentListResponse from a JSON string
agent_subagent_list_response_instance = AgentSubagentListResponse.from_json(json)
# print the JSON string representation of the object
print(AgentSubagentListResponse.to_json())

# convert the object into a dict
agent_subagent_list_response_dict = agent_subagent_list_response_instance.to_dict()
# create an instance of AgentSubagentListResponse from a dict
agent_subagent_list_response_from_dict = AgentSubagentListResponse.from_dict(agent_subagent_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


