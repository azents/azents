# AgentRuntimeExecutionPolicyStatusResponse

Safe server-authoritative Runtime execution-policy status.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | [**RuntimeExecutionPolicyStatus**](RuntimeExecutionPolicyStatus.md) |  | 
**configured** | [**RuntimeExecutionConfiguredSummaryResponse**](RuntimeExecutionConfiguredSummaryResponse.md) |  | 
**target** | [**RuntimeExecutionSnapshotSummaryResponse**](RuntimeExecutionSnapshotSummaryResponse.md) |  | 
**applied** | [**RuntimeExecutionSnapshotSummaryResponse**](RuntimeExecutionSnapshotSummaryResponse.md) |  | 
**desired_generation** | **int** |  | 
**governing_layers** | [**Dict[str, RuntimeExecutionPolicyLayer]**](RuntimeExecutionPolicyLayer.md) |  | 
**reason_codes** | **List[str]** |  | 
**required_action** | [**RuntimeExecutionRequiredAction**](RuntimeExecutionRequiredAction.md) |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_execution_policy_status_response import AgentRuntimeExecutionPolicyStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeExecutionPolicyStatusResponse from a JSON string
agent_runtime_execution_policy_status_response_instance = AgentRuntimeExecutionPolicyStatusResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeExecutionPolicyStatusResponse.to_json())

# convert the object into a dict
agent_runtime_execution_policy_status_response_dict = agent_runtime_execution_policy_status_response_instance.to_dict()
# create an instance of AgentRuntimeExecutionPolicyStatusResponse from a dict
agent_runtime_execution_policy_status_response_from_dict = AgentRuntimeExecutionPolicyStatusResponse.from_dict(agent_runtime_execution_policy_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


