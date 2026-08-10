# AgentRuntimeRemovalImpactResponse

Privacy-safe aggregate Runtime removal impact.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**active_root_session_count** | **int** |  | 
**active_subagent_count** | **int** |  | 
**active_run_count** | **int** |  | 
**queued_runtime_action_count** | **int** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_removal_impact_response import AgentRuntimeRemovalImpactResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeRemovalImpactResponse from a JSON string
agent_runtime_removal_impact_response_instance = AgentRuntimeRemovalImpactResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeRemovalImpactResponse.to_json())

# convert the object into a dict
agent_runtime_removal_impact_response_dict = agent_runtime_removal_impact_response_instance.to_dict()
# create an instance of AgentRuntimeRemovalImpactResponse from a dict
agent_runtime_removal_impact_response_from_dict = AgentRuntimeRemovalImpactResponse.from_dict(agent_runtime_removal_impact_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


