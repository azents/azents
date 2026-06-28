# AgentSessionListResponse

Conversation session list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[AgentSessionResponse]**](AgentSessionResponse.md) | Session list |

## Example

```python
from azentspublicclient.models.agent_session_list_response import AgentSessionListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionListResponse from a JSON string
agent_session_list_response_instance = AgentSessionListResponse.from_json(json)
# print the JSON string representation of the object
print(AgentSessionListResponse.to_json())

# convert the object into a dict
agent_session_list_response_dict = agent_session_list_response_instance.to_dict()
# create an instance of AgentSessionListResponse from a dict
agent_session_list_response_from_dict = AgentSessionListResponse.from_dict(agent_session_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


