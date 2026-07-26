# RuntimeExecutionCapabilitySummaryResponse

One safe Runtime execution capability summary.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**module_id** | [**RuntimeExecutionModuleId**](RuntimeExecutionModuleId.md) |  | 
**version** | **int** |  | 
**enabled** | **bool** |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_capability_summary_response import RuntimeExecutionCapabilitySummaryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionCapabilitySummaryResponse from a JSON string
runtime_execution_capability_summary_response_instance = RuntimeExecutionCapabilitySummaryResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionCapabilitySummaryResponse.to_json())

# convert the object into a dict
runtime_execution_capability_summary_response_dict = runtime_execution_capability_summary_response_instance.to_dict()
# create an instance of RuntimeExecutionCapabilitySummaryResponse from a dict
runtime_execution_capability_summary_response_from_dict = RuntimeExecutionCapabilitySummaryResponse.from_dict(runtime_execution_capability_summary_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


