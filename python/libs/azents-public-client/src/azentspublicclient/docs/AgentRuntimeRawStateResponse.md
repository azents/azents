# AgentRuntimeRawStateResponse

Agent Runtime raw state response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**workspace_id** | **str** |  | 
**agent_id** | **str** |  | 
**runtime_provider_id** | **str** |  | 
**provider_config** | **Dict[str, object]** |  | 
**desired_state** | [**RuntimeDesiredState**](RuntimeDesiredState.md) |  | 
**desired_generation** | **int** |  | 
**last_lifecycle_command** | [**RuntimeLifecycleCommandType**](RuntimeLifecycleCommandType.md) |  | 
**reset_final_desired_state** | [**RuntimeDesiredState**](RuntimeDesiredState.md) |  | 
**provider_observed_state** | [**RuntimeProviderObservedState**](RuntimeProviderObservedState.md) |  | 
**provider_observed_generation** | **int** |  | 
**provider_connection_state** | [**RuntimeProviderConnectionState**](RuntimeProviderConnectionState.md) |  | 
**runner_state** | [**RuntimeRunnerState**](RuntimeRunnerState.md) |  | 
**runner_generation** | **int** |  | 
**workspace_path** | **str** |  | 
**failure_generation** | **int** |  | 
**failure_code** | **str** |  | 
**failure_message** | **str** |  | 
**last_state_change_at** | **datetime** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_raw_state_response import AgentRuntimeRawStateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeRawStateResponse from a JSON string
agent_runtime_raw_state_response_instance = AgentRuntimeRawStateResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeRawStateResponse.to_json())

# convert the object into a dict
agent_runtime_raw_state_response_dict = agent_runtime_raw_state_response_instance.to_dict()
# create an instance of AgentRuntimeRawStateResponse from a dict
agent_runtime_raw_state_response_from_dict = AgentRuntimeRawStateResponse.from_dict(agent_runtime_raw_state_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


