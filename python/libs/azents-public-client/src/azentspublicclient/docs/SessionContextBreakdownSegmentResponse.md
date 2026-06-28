# SessionContextBreakdownSegmentResponse

Session context breakdown segment response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**key** | **str** | Breakdown key |
**tokens** | **int** | Prompt character count |
**percent** | **float** | Known prompt character percentage |

## Example

```python
from azentspublicclient.models.session_context_breakdown_segment_response import SessionContextBreakdownSegmentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionContextBreakdownSegmentResponse from a JSON string
session_context_breakdown_segment_response_instance = SessionContextBreakdownSegmentResponse.from_json(json)
# print the JSON string representation of the object
print(SessionContextBreakdownSegmentResponse.to_json())

# convert the object into a dict
session_context_breakdown_segment_response_dict = session_context_breakdown_segment_response_instance.to_dict()
# create an instance of SessionContextBreakdownSegmentResponse from a dict
session_context_breakdown_segment_response_from_dict = SessionContextBreakdownSegmentResponse.from_dict(session_context_breakdown_segment_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


