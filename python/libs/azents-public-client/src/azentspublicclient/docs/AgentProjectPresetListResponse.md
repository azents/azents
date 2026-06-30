# AgentProjectPresetListResponse

Agent Project preset list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[AgentProjectPresetResponse]**](AgentProjectPresetResponse.md) | Project presets | 

## Example

```python
from azentspublicclient.models.agent_project_preset_list_response import AgentProjectPresetListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentProjectPresetListResponse from a JSON string
agent_project_preset_list_response_instance = AgentProjectPresetListResponse.from_json(json)
# print the JSON string representation of the object
print(AgentProjectPresetListResponse.to_json())

# convert the object into a dict
agent_project_preset_list_response_dict = agent_project_preset_list_response_instance.to_dict()
# create an instance of AgentProjectPresetListResponse from a dict
agent_project_preset_list_response_from_dict = AgentProjectPresetListResponse.from_dict(agent_project_preset_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


