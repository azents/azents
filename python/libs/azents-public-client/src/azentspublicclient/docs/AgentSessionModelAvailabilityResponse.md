# AgentSessionModelAvailabilityResponse

Authoritative Session model availability response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**semantic_label** | **str** |  | 
**primary** | [**ModelCandidateIdentity**](ModelCandidateIdentity.md) |  | 
**primary_display_name** | **str** |  | 
**state** | **str** |  | 
**deadline** | **datetime** |  | 
**server_time** | **datetime** |  | 
**first_usable_fallback_display_name** | **str** |  | 
**reservation** | [**PrimaryModelReservation**](PrimaryModelReservation.md) |  | 

## Example

```python
from azentspublicclient.models.agent_session_model_availability_response import AgentSessionModelAvailabilityResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionModelAvailabilityResponse from a JSON string
agent_session_model_availability_response_instance = AgentSessionModelAvailabilityResponse.from_json(json)
# print the JSON string representation of the object
print(AgentSessionModelAvailabilityResponse.to_json())

# convert the object into a dict
agent_session_model_availability_response_dict = agent_session_model_availability_response_instance.to_dict()
# create an instance of AgentSessionModelAvailabilityResponse from a dict
agent_session_model_availability_response_from_dict = AgentSessionModelAvailabilityResponse.from_dict(agent_session_model_availability_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


