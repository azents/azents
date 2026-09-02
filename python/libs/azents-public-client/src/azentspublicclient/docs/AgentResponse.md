# AgentResponse

Agent response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**name** | **str** |  | 
**description** | **str** |  | 
**model_selection** | [**AgentModelSelection**](AgentModelSelection.md) |  | 
**lightweight_model_selection** | [**AgentModelSelection**](AgentModelSelection.md) |  | 
**selectable_model_options** | [**List[SelectableModelOption]**](SelectableModelOption.md) |  | 
**main_model_label** | **str** |  | 
**lightweight_model_label** | **str** |  | 
**effective_context_window_tokens** | **int** |  | 
**effective_auto_compaction_threshold_tokens** | **int** |  | 
**model_parameters** | [**ModelParameters**](ModelParameters.md) |  | 
**system_prompt** | **str** |  | 
**enabled** | **bool** |  | 
**type** | [**AgentType**](AgentType.md) |  | 
**runtime_profile_id** | **str** |  | 
**runtime_profile_selection_version** | **int** |  | 
**runtime_profile_available** | **bool** |  | 
**runtime_profile_availability_reason_code** | **str** |  | 
**runtime_capability** | [**AgentRuntimeCapability**](AgentRuntimeCapability.md) |  | 
**runtime_capability_version** | **int** |  | 
**runtime_profile_configuration_status** | **str** |  | 
**runtime_add_available** | **bool** |  | 
**runtime_remove_available** | **bool** |  | 
**terminal_enabled** | **bool** |  | 
**infrastructure_terminal_enabled** | **bool** |  | 
**workspace_terminal_enabled** | **bool** |  | 
**effective_terminal_enabled** | **bool** |  | 
**terminal_denied_scope** | **str** |  | 
**memory_enabled** | **bool** |  | 
**tool_search_enabled** | **bool** |  | 
**max_turns** | **int** |  | 
**auto_archive_ttl_days** | **int** | Inactivity period before automatic Session archive | 
**subagent_settings** | [**SubagentSettings**](SubagentSettings.md) |  | 
**avatar** | [**UploadedImage**](UploadedImage.md) |  | [optional] 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.agent_response import AgentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentResponse from a JSON string
agent_response_instance = AgentResponse.from_json(json)
# print the JSON string representation of the object
print(AgentResponse.to_json())

# convert the object into a dict
agent_response_dict = agent_response_instance.to_dict()
# create an instance of AgentResponse from a dict
agent_response_from_dict = AgentResponse.from_dict(agent_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


