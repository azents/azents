# RuntimeExecutionSnapshotSummaryResponse

Safe target or applied Runtime execution-policy summary.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**profile_id** | **str** |  | 
**digest** | **str** |  | 
**desired_generation** | **int** |  | 
**capabilities** | [**List[RuntimeExecutionCapabilitySummaryResponse]**](RuntimeExecutionCapabilitySummaryResponse.md) |  | 
**storage_mode** | [**RuntimeExecutionStorageMode**](RuntimeExecutionStorageMode.md) |  | 
**storage_capacity_bytes** | **int** |  | 
**network_mode** | [**RuntimeExecutionNetworkMode**](RuntimeExecutionNetworkMode.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_snapshot_summary_response import RuntimeExecutionSnapshotSummaryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionSnapshotSummaryResponse from a JSON string
runtime_execution_snapshot_summary_response_instance = RuntimeExecutionSnapshotSummaryResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionSnapshotSummaryResponse.to_json())

# convert the object into a dict
runtime_execution_snapshot_summary_response_dict = runtime_execution_snapshot_summary_response_instance.to_dict()
# create an instance of RuntimeExecutionSnapshotSummaryResponse from a dict
runtime_execution_snapshot_summary_response_from_dict = RuntimeExecutionSnapshotSummaryResponse.from_dict(runtime_execution_snapshot_summary_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


