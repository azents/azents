# SessionDiagnosticEvent

Safe canonical event projection, including retained reverted records.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**event_id** | **str** |  | 
**kind** | [**EventKind**](EventKind.md) |  | 
**created_at** | **datetime** |  | 
**reverted** | **bool** |  | 
**text** | **str** |  | 
**tool_name** | **str** |  | 
**call_id** | **str** |  | 
**tool_status** | **str** |  | 
**arguments** | **str** |  | 
**arguments_omitted** | **bool** |  | 
**truncated** | **bool** |  | 

## Example

```python
from azentsadminclient.models.session_diagnostic_event import SessionDiagnosticEvent

# TODO update the JSON string below
json = "{}"
# create an instance of SessionDiagnosticEvent from a JSON string
session_diagnostic_event_instance = SessionDiagnosticEvent.from_json(json)
# print the JSON string representation of the object
print(SessionDiagnosticEvent.to_json())

# convert the object into a dict
session_diagnostic_event_dict = session_diagnostic_event_instance.to_dict()
# create an instance of SessionDiagnosticEvent from a dict
session_diagnostic_event_from_dict = SessionDiagnosticEvent.from_dict(session_diagnostic_event_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


