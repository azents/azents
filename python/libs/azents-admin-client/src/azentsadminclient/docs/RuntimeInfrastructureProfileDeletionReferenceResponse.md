# RuntimeInfrastructureProfileDeletionReferenceResponse

One current Workspace Runtime Profile reference and bounded usage.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workspace_id** | **str** |  | 
**workspace_name** | **str** |  | 
**workspace_handle** | **str** |  | 
**workspace_runtime_profile_id** | **str** |  | 
**workspace_runtime_profile_display_name** | **str** |  | 
**workspace_runtime_profile_lifecycle** | [**RuntimeProfileLifecycle**](RuntimeProfileLifecycle.md) |  | 
**workspace_runtime_profile_version** | **int** |  | 
**selected_agent_count** | **int** |  | 
**running_runtime_count** | **int** |  | 

## Example

```python
from azentsadminclient.models.runtime_infrastructure_profile_deletion_reference_response import RuntimeInfrastructureProfileDeletionReferenceResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeInfrastructureProfileDeletionReferenceResponse from a JSON string
runtime_infrastructure_profile_deletion_reference_response_instance = RuntimeInfrastructureProfileDeletionReferenceResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeInfrastructureProfileDeletionReferenceResponse.to_json())

# convert the object into a dict
runtime_infrastructure_profile_deletion_reference_response_dict = runtime_infrastructure_profile_deletion_reference_response_instance.to_dict()
# create an instance of RuntimeInfrastructureProfileDeletionReferenceResponse from a dict
runtime_infrastructure_profile_deletion_reference_response_from_dict = RuntimeInfrastructureProfileDeletionReferenceResponse.from_dict(runtime_infrastructure_profile_deletion_reference_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


