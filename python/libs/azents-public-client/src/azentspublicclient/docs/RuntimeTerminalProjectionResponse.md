# RuntimeTerminalProjectionResponse

Session Terminal availability and action projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**state** | **str** |  | 
**reason_code** | [**RuntimeTerminalReasonCode**](RuntimeTerminalReasonCode.md) |  | 
**denied_scope** | [**RuntimeTerminalDeniedScope**](RuntimeTerminalDeniedScope.md) |  | 
**can_start_runtime** | **bool** |  | 
**can_open_or_attach** | **bool** |  | 
**terminal** | [**RuntimeTerminalSummaryResponse**](RuntimeTerminalSummaryResponse.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_terminal_projection_response import RuntimeTerminalProjectionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeTerminalProjectionResponse from a JSON string
runtime_terminal_projection_response_instance = RuntimeTerminalProjectionResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeTerminalProjectionResponse.to_json())

# convert the object into a dict
runtime_terminal_projection_response_dict = runtime_terminal_projection_response_instance.to_dict()
# create an instance of RuntimeTerminalProjectionResponse from a dict
runtime_terminal_projection_response_from_dict = RuntimeTerminalProjectionResponse.from_dict(runtime_terminal_projection_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


