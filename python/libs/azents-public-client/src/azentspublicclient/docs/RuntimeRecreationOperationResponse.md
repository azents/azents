# RuntimeRecreationOperationResponse

Durable recreation operation progress and bounded item details.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**target_kind** | [**RuntimeRecreationTargetKind**](RuntimeRecreationTargetKind.md) |  | 
**target_id** | **str** |  | 
**target_version** | **str** |  | 
**status** | [**RuntimeRecreationOperationStatus**](RuntimeRecreationOperationStatus.md) |  | 
**concurrency_limit** | **int** |  | 
**total_count** | **int** |  | 
**pending_count** | **int** |  | 
**running_count** | **int** |  | 
**succeeded_count** | **int** |  | 
**skipped_count** | **int** |  | 
**failed_count** | **int** |  | 
**created_at** | **datetime** |  | 
**started_at** | **datetime** |  | 
**completed_at** | **datetime** |  | 
**items** | [**List[RuntimeRecreationItemResponse]**](RuntimeRecreationItemResponse.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_recreation_operation_response import RuntimeRecreationOperationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeRecreationOperationResponse from a JSON string
runtime_recreation_operation_response_instance = RuntimeRecreationOperationResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeRecreationOperationResponse.to_json())

# convert the object into a dict
runtime_recreation_operation_response_dict = runtime_recreation_operation_response_instance.to_dict()
# create an instance of RuntimeRecreationOperationResponse from a dict
runtime_recreation_operation_response_from_dict = RuntimeRecreationOperationResponse.from_dict(runtime_recreation_operation_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


