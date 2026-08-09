# AgentRuntimeConfigurationStatusResponse

Desired and applied Runtime configuration status.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | **str** |  | 
**desired** | [**RuntimeConfigurationRevisionResponse**](RuntimeConfigurationRevisionResponse.md) |  | 
**applied** | [**RuntimeConfigurationRevisionResponse**](RuntimeConfigurationRevisionResponse.md) |  | 
**containment** | [**RuntimeContainmentStatus**](RuntimeContainmentStatus.md) |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_configuration_status_response import AgentRuntimeConfigurationStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeConfigurationStatusResponse from a JSON string
agent_runtime_configuration_status_response_instance = AgentRuntimeConfigurationStatusResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeConfigurationStatusResponse.to_json())

# convert the object into a dict
agent_runtime_configuration_status_response_dict = agent_runtime_configuration_status_response_instance.to_dict()
# create an instance of AgentRuntimeConfigurationStatusResponse from a dict
agent_runtime_configuration_status_response_from_dict = AgentRuntimeConfigurationStatusResponse.from_dict(agent_runtime_configuration_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


