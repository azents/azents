# RuntimeTerminalSummaryResponse

Content-free visible Terminal summary.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**terminal_id** | **str** |  | 
**lifecycle** | [**RuntimeTerminalLifecycle**](RuntimeTerminalLifecycle.md) |  | 
**attached** | **bool** |  | 
**started_at** | **datetime** |  | 
**ended_at** | **datetime** |  | 
**final_reason** | **str** |  | 
**input_bytes** | **int** |  | 
**output_bytes** | **int** |  | 
**replay_truncated** | **bool** |  | 

## Example

```python
from azentspublicclient.models.runtime_terminal_summary_response import RuntimeTerminalSummaryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeTerminalSummaryResponse from a JSON string
runtime_terminal_summary_response_instance = RuntimeTerminalSummaryResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeTerminalSummaryResponse.to_json())

# convert the object into a dict
runtime_terminal_summary_response_dict = runtime_terminal_summary_response_instance.to_dict()
# create an instance of RuntimeTerminalSummaryResponse from a dict
runtime_terminal_summary_response_from_dict = RuntimeTerminalSummaryResponse.from_dict(runtime_terminal_summary_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


