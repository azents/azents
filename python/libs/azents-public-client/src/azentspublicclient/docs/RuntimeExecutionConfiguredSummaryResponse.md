# RuntimeExecutionConfiguredSummaryResponse

Safe configured Runtime execution-policy summary.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**profile_id** | **str** |  | 
**digest** | **str** |  | 
**capabilities** | [**List[RuntimeExecutionCapabilitySummaryResponse]**](RuntimeExecutionCapabilitySummaryResponse.md) |  | 
**storage_mode** | [**RuntimeExecutionStorageMode**](RuntimeExecutionStorageMode.md) |  | 
**storage_capacity_bytes** | **int** |  | 
**network_mode** | [**RuntimeExecutionNetworkMode**](RuntimeExecutionNetworkMode.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_configured_summary_response import RuntimeExecutionConfiguredSummaryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionConfiguredSummaryResponse from a JSON string
runtime_execution_configured_summary_response_instance = RuntimeExecutionConfiguredSummaryResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionConfiguredSummaryResponse.to_json())

# convert the object into a dict
runtime_execution_configured_summary_response_dict = runtime_execution_configured_summary_response_instance.to_dict()
# create an instance of RuntimeExecutionConfiguredSummaryResponse from a dict
runtime_execution_configured_summary_response_from_dict = RuntimeExecutionConfiguredSummaryResponse.from_dict(runtime_execution_configured_summary_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


