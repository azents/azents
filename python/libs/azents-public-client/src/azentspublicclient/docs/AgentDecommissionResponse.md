# AgentDecommissionResponse

Accepted Agent decommission response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**job_id** | **str** |  | 
**status** | **str** |  | 
**created_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.agent_decommission_response import AgentDecommissionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentDecommissionResponse from a JSON string
agent_decommission_response_instance = AgentDecommissionResponse.from_json(json)
# print the JSON string representation of the object
print(AgentDecommissionResponse.to_json())

# convert the object into a dict
agent_decommission_response_dict = agent_decommission_response_instance.to_dict()
# create an instance of AgentDecommissionResponse from a dict
agent_decommission_response_from_dict = AgentDecommissionResponse.from_dict(agent_decommission_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


