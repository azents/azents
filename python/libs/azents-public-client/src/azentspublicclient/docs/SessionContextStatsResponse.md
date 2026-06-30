# SessionContextStatsResponse

Session context statistics response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**total_events** | **int** | Raw event count | 
**user_messages** | **int** | User message count | 
**assistant_messages** | **int** | Assistant message count | 
**reasoning_events** | **int** | Reasoning event count | 
**tool_calls** | **int** | Tool call count | 
**tool_results** | **int** | Tool result count | 
**turn_markers** | **int** | Turn marker count | 
**total_cost_usd** | **float** |  | [optional] 

## Example

```python
from azentspublicclient.models.session_context_stats_response import SessionContextStatsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionContextStatsResponse from a JSON string
session_context_stats_response_instance = SessionContextStatsResponse.from_json(json)
# print the JSON string representation of the object
print(SessionContextStatsResponse.to_json())

# convert the object into a dict
session_context_stats_response_dict = session_context_stats_response_instance.to_dict()
# create an instance of SessionContextStatsResponse from a dict
session_context_stats_response_from_dict = SessionContextStatsResponse.from_dict(session_context_stats_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


