# RuntimeConfigurationStateResponse

Bounded desired or applied Runtime configuration state.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**sequence** | **int** |  | 
**status** | **str** |  | 
**target_generation** | **int** |  | 
**digest** | **str** |  | 
**provider_id** | **str** |  | 
**provider_capability_revision_id** | **str** |  | 
**infrastructure_profile_id** | **str** |  | 
**infrastructure_profile_version** | **int** |  | 
**workspace_runtime_profile_id** | **str** |  | 
**workspace_runtime_profile_version** | **int** |  | 
**agent_selection_version** | **int** |  | 
**required_capabilities** | **List[str]** |  | 
**missing_capabilities** | **List[str]** |  | 
**reason_code** | **str** |  | 
**provider_reported_digest** | **str** |  | 
**runner_reported_digest** | **str** |  | 
**provider_acknowledged_at** | **datetime** |  | 
**runner_observed_at** | **datetime** |  | 
**applied_at** | **datetime** |  | 
**network** | [**RuntimeConfigurationNetworkResponse**](RuntimeConfigurationNetworkResponse.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_configuration_state_response import RuntimeConfigurationStateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeConfigurationStateResponse from a JSON string
runtime_configuration_state_response_instance = RuntimeConfigurationStateResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeConfigurationStateResponse.to_json())

# convert the object into a dict
runtime_configuration_state_response_dict = runtime_configuration_state_response_instance.to_dict()
# create an instance of RuntimeConfigurationStateResponse from a dict
runtime_configuration_state_response_from_dict = RuntimeConfigurationStateResponse.from_dict(runtime_configuration_state_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


