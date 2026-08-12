# RuntimeInfrastructureProfileDeleteResponse

Bounded outcome from one infrastructure Profile deletion.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**profile_id** | **str** |  | 
**superseded_recreation_operation_count** | **int** |  | 
**skipped_recreation_item_count** | **int** |  | 

## Example

```python
from azentsadminclient.models.runtime_infrastructure_profile_delete_response import RuntimeInfrastructureProfileDeleteResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeInfrastructureProfileDeleteResponse from a JSON string
runtime_infrastructure_profile_delete_response_instance = RuntimeInfrastructureProfileDeleteResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeInfrastructureProfileDeleteResponse.to_json())

# convert the object into a dict
runtime_infrastructure_profile_delete_response_dict = runtime_infrastructure_profile_delete_response_instance.to_dict()
# create an instance of RuntimeInfrastructureProfileDeleteResponse from a dict
runtime_infrastructure_profile_delete_response_from_dict = RuntimeInfrastructureProfileDeleteResponse.from_dict(runtime_infrastructure_profile_delete_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


