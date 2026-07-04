# AgentSessionProjectDefaultsResponse

New AgentSession Project defaults response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**project_paths** | **List[str]** | Default selected Project paths |
**items** | [**List[AgentSessionProjectDefaultsResponseItemsInner]**](AgentSessionProjectDefaultsResponseItemsInner.md) | Default selected workspace items |
**source** | [**AgentSessionProjectDefaultsSourceResponse**](AgentSessionProjectDefaultsSourceResponse.md) | Default source metadata |

## Example

```python
from azentspublicclient.models.agent_session_project_defaults_response import AgentSessionProjectDefaultsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionProjectDefaultsResponse from a JSON string
agent_session_project_defaults_response_instance = AgentSessionProjectDefaultsResponse.from_json(json)
# print the JSON string representation of the object
print(AgentSessionProjectDefaultsResponse.to_json())

# convert the object into a dict
agent_session_project_defaults_response_dict = agent_session_project_defaults_response_instance.to_dict()
# create an instance of AgentSessionProjectDefaultsResponse from a dict
agent_session_project_defaults_response_from_dict = AgentSessionProjectDefaultsResponse.from_dict(agent_session_project_defaults_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


