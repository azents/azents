# RuntimeInfrastructureProfileDeletionImpactResponse

Fresh deletion impact for one exact infrastructure Profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**profile_id** | **str** |  | 
**profile_kind** | **str** |  | 
**display_name** | **str** |  | 
**version** | **int** |  | 
**blocking_reference_count** | **int** |  | 
**references** | [**List[RuntimeInfrastructureProfileDeletionReferenceResponse]**](RuntimeInfrastructureProfileDeletionReferenceResponse.md) |  | 
**applied_only_running_runtime_count** | **int** |  | 
**offset** | **int** |  | 
**limit** | **int** |  | 

## Example

```python
from azentsadminclient.models.runtime_infrastructure_profile_deletion_impact_response import RuntimeInfrastructureProfileDeletionImpactResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeInfrastructureProfileDeletionImpactResponse from a JSON string
runtime_infrastructure_profile_deletion_impact_response_instance = RuntimeInfrastructureProfileDeletionImpactResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeInfrastructureProfileDeletionImpactResponse.to_json())

# convert the object into a dict
runtime_infrastructure_profile_deletion_impact_response_dict = runtime_infrastructure_profile_deletion_impact_response_instance.to_dict()
# create an instance of RuntimeInfrastructureProfileDeletionImpactResponse from a dict
runtime_infrastructure_profile_deletion_impact_response_from_dict = RuntimeInfrastructureProfileDeletionImpactResponse.from_dict(runtime_infrastructure_profile_deletion_impact_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


