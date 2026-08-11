# RuntimeInfrastructureProfileResponse

One Provider-owned infrastructure Profile with compatibility evidence.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**profile_kind** | **str** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**lifecycle** | [**RuntimeProfileLifecycle**](RuntimeProfileLifecycle.md) |  | 
**contract_family** | **str** |  | 
**schema_version** | **int** |  | 
**spec** | [**RuntimeInfrastructureProfileSpec**](RuntimeInfrastructureProfileSpec.md) |  | 
**required_capabilities** | **List[str]** |  | 
**version** | **int** |  | 
**digest** | **str** |  | 
**compatible** | **bool** |  | 
**compatibility_reason_code** | **str** |  | 
**missing_capabilities** | **List[str]** |  | 
**incompatible_constraints** | **List[str]** |  | 
**capability_revision_id** | **str** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.runtime_infrastructure_profile_response import RuntimeInfrastructureProfileResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeInfrastructureProfileResponse from a JSON string
runtime_infrastructure_profile_response_instance = RuntimeInfrastructureProfileResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeInfrastructureProfileResponse.to_json())

# convert the object into a dict
runtime_infrastructure_profile_response_dict = runtime_infrastructure_profile_response_instance.to_dict()
# create an instance of RuntimeInfrastructureProfileResponse from a dict
runtime_infrastructure_profile_response_from_dict = RuntimeInfrastructureProfileResponse.from_dict(runtime_infrastructure_profile_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


