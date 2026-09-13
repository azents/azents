# AgentSessionPrimaryModelReserveRequest

Request one exact Primary recovery reservation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**semantic_label** | **str** |  | 
**primary** | [**ModelCandidateIdentity**](ModelCandidateIdentity.md) |  | 

## Example

```python
from azentspublicclient.models.agent_session_primary_model_reserve_request import AgentSessionPrimaryModelReserveRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionPrimaryModelReserveRequest from a JSON string
agent_session_primary_model_reserve_request_instance = AgentSessionPrimaryModelReserveRequest.from_json(json)
# print the JSON string representation of the object
print(AgentSessionPrimaryModelReserveRequest.to_json())

# convert the object into a dict
agent_session_primary_model_reserve_request_dict = agent_session_primary_model_reserve_request_instance.to_dict()
# create an instance of AgentSessionPrimaryModelReserveRequest from a dict
agent_session_primary_model_reserve_request_from_dict = AgentSessionPrimaryModelReserveRequest.from_dict(agent_session_primary_model_reserve_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


