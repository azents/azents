# AgentRuntimeExecutionPolicyApplyResponse

Exact immutable Runtime target created or reused by Agent Apply.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**snapshot_id** | **str** |  | 
**desired_generation** | **int** |  | 
**target_digest** | **str** |  | 
**created** | **bool** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_execution_policy_apply_response import AgentRuntimeExecutionPolicyApplyResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeExecutionPolicyApplyResponse from a JSON string
agent_runtime_execution_policy_apply_response_instance = AgentRuntimeExecutionPolicyApplyResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeExecutionPolicyApplyResponse.to_json())

# convert the object into a dict
agent_runtime_execution_policy_apply_response_dict = agent_runtime_execution_policy_apply_response_instance.to_dict()
# create an instance of AgentRuntimeExecutionPolicyApplyResponse from a dict
agent_runtime_execution_policy_apply_response_from_dict = AgentRuntimeExecutionPolicyApplyResponse.from_dict(agent_runtime_execution_policy_apply_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


