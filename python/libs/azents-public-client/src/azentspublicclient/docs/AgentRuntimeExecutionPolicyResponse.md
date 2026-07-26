# AgentRuntimeExecutionPolicyResponse

Configured Agent intent and hierarchy-only effective preview.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** |  | 
**version** | **int** |  | 
**profile_id** | **str** |  | 
**profile_version** | **int** |  | 
**profile_lifecycle** | [**RuntimeExecutionProfileLifecycle**](RuntimeExecutionProfileLifecycle.md) |  | 
**restriction** | [**RuntimeExecutionPolicyRestriction**](RuntimeExecutionPolicyRestriction.md) |  | 
**digest** | **str** |  | 
**effective_preview** | [**RuntimeExecutionResolution**](RuntimeExecutionResolution.md) |  | 
**provider_compatibility_evaluated** | **bool** |  | 
**updated_at** | **datetime** |  | 
**capabilities** | [**RuntimeExecutionManagementCapabilitiesResponse**](RuntimeExecutionManagementCapabilitiesResponse.md) |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_execution_policy_response import AgentRuntimeExecutionPolicyResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeExecutionPolicyResponse from a JSON string
agent_runtime_execution_policy_response_instance = AgentRuntimeExecutionPolicyResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeExecutionPolicyResponse.to_json())

# convert the object into a dict
agent_runtime_execution_policy_response_dict = agent_runtime_execution_policy_response_instance.to_dict()
# create an instance of AgentRuntimeExecutionPolicyResponse from a dict
agent_runtime_execution_policy_response_from_dict = AgentRuntimeExecutionPolicyResponse.from_dict(agent_runtime_execution_policy_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


