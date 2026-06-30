# AgentSessionProjectDefaultsSourceResponse

New AgentSession Project defaults source metadata response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Default source type | 
**session_id** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.agent_session_project_defaults_source_response import AgentSessionProjectDefaultsSourceResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionProjectDefaultsSourceResponse from a JSON string
agent_session_project_defaults_source_response_instance = AgentSessionProjectDefaultsSourceResponse.from_json(json)
# print the JSON string representation of the object
print(AgentSessionProjectDefaultsSourceResponse.to_json())

# convert the object into a dict
agent_session_project_defaults_source_response_dict = agent_session_project_defaults_source_response_instance.to_dict()
# create an instance of AgentSessionProjectDefaultsSourceResponse from a dict
agent_session_project_defaults_source_response_from_dict = AgentSessionProjectDefaultsSourceResponse.from_dict(agent_session_project_defaults_source_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


