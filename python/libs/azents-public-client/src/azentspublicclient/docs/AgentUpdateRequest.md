# AgentUpdateRequest

Agent update request, for partial updates.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Agent name | [optional] 
**description** | **str** |  | [optional] 
**model_selection** | [**AgentModelSelectionInput**](AgentModelSelectionInput.md) |  | [optional] 
**lightweight_model_selection** | [**AgentModelSelectionInput**](AgentModelSelectionInput.md) |  | [optional] 
**selectable_model_options** | [**List[SelectableModelOptionInput]**](SelectableModelOptionInput.md) |  | [optional] 
**main_model_label** | **str** |  | [optional] 
**lightweight_model_label** | **str** |  | [optional] 
**model_parameters** | [**ModelParameters**](ModelParameters.md) |  | [optional] 
**system_prompt** | **str** |  | [optional] 
**enabled** | **bool** | Enabled state | [optional] 
**type** | [**AgentType**](AgentType.md) | Visibility scope | [optional] 
**runtime_provider_id** | **str** |  | [optional] 
**shell_enabled** | **bool** | Shell enabled state | [optional] 
**memory_enabled** | **bool** | Memory enabled state | [optional] 
**max_turns** | **int** |  | [optional] 
**subagent_settings** | [**SubagentSettings**](SubagentSettings.md) | Subagent execution settings | [optional] 

## Example

```python
from azentspublicclient.models.agent_update_request import AgentUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentUpdateRequest from a JSON string
agent_update_request_instance = AgentUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(AgentUpdateRequest.to_json())

# convert the object into a dict
agent_update_request_dict = agent_update_request_instance.to_dict()
# create an instance of AgentUpdateRequest from a dict
agent_update_request_from_dict = AgentUpdateRequest.from_dict(agent_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


