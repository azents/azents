# AgentRuntimeSummaryResponse

Agent Runtime summary response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**summary** | [**RuntimeSummary**](RuntimeSummary.md) |  | 
**actions** | [**AgentRuntimeActionsResponse**](AgentRuntimeActionsResponse.md) |  | 
**failure** | [**AgentRuntimeFailureResponse**](AgentRuntimeFailureResponse.md) |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_summary_response import AgentRuntimeSummaryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeSummaryResponse from a JSON string
agent_runtime_summary_response_instance = AgentRuntimeSummaryResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeSummaryResponse.to_json())

# convert the object into a dict
agent_runtime_summary_response_dict = agent_runtime_summary_response_instance.to_dict()
# create an instance of AgentRuntimeSummaryResponse from a dict
agent_runtime_summary_response_from_dict = AgentRuntimeSummaryResponse.from_dict(agent_runtime_summary_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


