# SessionContextResponse

Agent session context inspector response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session** | [**SessionContextSessionResponse**](SessionContextSessionResponse.md) | Session summary |
**usage** | **Dict[str, object]** |  | [optional]
**stats** | [**SessionContextStatsResponse**](SessionContextStatsResponse.md) | Aggregate stats |
**breakdown** | [**List[SessionContextBreakdownSegmentResponse]**](SessionContextBreakdownSegmentResponse.md) | Prompt character breakdown |
**system_prompt** | [**SessionContextSystemPromptResponse**](SessionContextSystemPromptResponse.md) |  | [optional]
**raw_events** | [**List[SessionContextRawEventResponse]**](SessionContextRawEventResponse.md) | Raw events |

## Example

```python
from azentspublicclient.models.session_context_response import SessionContextResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionContextResponse from a JSON string
session_context_response_instance = SessionContextResponse.from_json(json)
# print the JSON string representation of the object
print(SessionContextResponse.to_json())

# convert the object into a dict
session_context_response_dict = session_context_response_instance.to_dict()
# create an instance of SessionContextResponse from a dict
session_context_response_from_dict = SessionContextResponse.from_dict(session_context_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
