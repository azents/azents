# AgentCreateRequest

Agent creation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Agent name |
**model_selection** | [**AgentModelSelectionInput**](AgentModelSelectionInput.md) |  | [optional]
**lightweight_model_selection** | [**AgentModelSelectionInput**](AgentModelSelectionInput.md) |  | [optional]
**selectable_model_options** | [**List[SelectableModelOptionInput]**](SelectableModelOptionInput.md) |  | [optional]
**main_model_label** | **str** |  | [optional]
**lightweight_model_label** | **str** |  | [optional]
**description** | **str** |  | [optional]
**model_parameters** | [**ModelParameters**](ModelParameters.md) |  | [optional]
**system_prompt** | **str** |  | [optional]
**enabled** | **bool** | Enabled state | [optional] [default to True]
**type** | [**AgentType**](AgentType.md) | Visibility scope | [optional]
**runtime_provider_id** | **str** |  | [optional]
**shell_enabled** | **bool** | Shell enabled state | [optional] [default to True]
**memory_enabled** | **bool** | Memory enabled state | [optional] [default to True]
**max_turns** | **int** |  | [optional]
**subagent_settings** | [**SubagentSettings**](SubagentSettings.md) | Subagent execution settings | [optional]

## Example

```python
from azentspublicclient.models.agent_create_request import AgentCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentCreateRequest from a JSON string
agent_create_request_instance = AgentCreateRequest.from_json(json)
# print the JSON string representation of the object
print(AgentCreateRequest.to_json())

# convert the object into a dict
agent_create_request_dict = agent_create_request_instance.to_dict()
# create an instance of AgentCreateRequest from a dict
agent_create_request_from_dict = AgentCreateRequest.from_dict(agent_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


