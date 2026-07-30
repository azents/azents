# RuntimeConfigurationRevisionResponse

Safe immutable Runtime configuration revision evidence.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**provider_id** | **str** |  | 
**provider_capability_revision_id** | **str** |  | 
**infrastructure_profile_id** | **str** |  | 
**infrastructure_profile_version** | **int** |  | 
**workspace_runtime_profile_id** | **str** |  | 
**workspace_runtime_profile_version** | **int** |  | 
**agent_selection_version** | **int** |  | 
**resolution_status** | [**RuntimeConfigurationResolutionStatus**](RuntimeConfigurationResolutionStatus.md) |  | 
**reason_code** | **str** |  | 
**required_capabilities** | **List[str]** |  | 
**missing_capabilities** | **List[str]** |  | 
**digest** | **str** |  | 
**target_desired_generation** | **int** |  | 
**provider_reported_digest** | **str** |  | 
**runner_reported_digest** | **str** |  | 
**provider_acknowledged_at** | **datetime** |  | 
**runtime_observed_at** | **datetime** |  | 
**created_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.runtime_configuration_revision_response import RuntimeConfigurationRevisionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeConfigurationRevisionResponse from a JSON string
runtime_configuration_revision_response_instance = RuntimeConfigurationRevisionResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeConfigurationRevisionResponse.to_json())

# convert the object into a dict
runtime_configuration_revision_response_dict = runtime_configuration_revision_response_instance.to_dict()
# create an instance of RuntimeConfigurationRevisionResponse from a dict
runtime_configuration_revision_response_from_dict = RuntimeConfigurationRevisionResponse.from_dict(runtime_configuration_revision_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


