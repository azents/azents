# AgentProjectPresetResponse

Agent Project preset response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Project preset ID | 
**path** | **str** | Agent Workspace absolute path | 
**created_at** | **datetime** | Created time | 
**updated_at** | **datetime** | Updated time | 

## Example

```python
from azentspublicclient.models.agent_project_preset_response import AgentProjectPresetResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentProjectPresetResponse from a JSON string
agent_project_preset_response_instance = AgentProjectPresetResponse.from_json(json)
# print the JSON string representation of the object
print(AgentProjectPresetResponse.to_json())

# convert the object into a dict
agent_project_preset_response_dict = agent_project_preset_response_instance.to_dict()
# create an instance of AgentProjectPresetResponse from a dict
agent_project_preset_response_from_dict = AgentProjectPresetResponse.from_dict(agent_project_preset_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


