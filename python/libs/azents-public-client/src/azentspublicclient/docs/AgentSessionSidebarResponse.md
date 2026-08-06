# AgentSessionSidebarResponse

Bounded Agent sidebar session response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**pinned** | [**List[AgentSessionResponse]**](AgentSessionResponse.md) | All pinned active root sessions | 
**recent** | [**List[AgentSessionResponse]**](AgentSessionResponse.md) | Distinct recent non-pinned active root sessions | 

## Example

```python
from azentspublicclient.models.agent_session_sidebar_response import AgentSessionSidebarResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionSidebarResponse from a JSON string
agent_session_sidebar_response_instance = AgentSessionSidebarResponse.from_json(json)
# print the JSON string representation of the object
print(AgentSessionSidebarResponse.to_json())

# convert the object into a dict
agent_session_sidebar_response_dict = agent_session_sidebar_response_instance.to_dict()
# create an instance of AgentSessionSidebarResponse from a dict
agent_session_sidebar_response_from_dict = AgentSessionSidebarResponse.from_dict(agent_session_sidebar_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


