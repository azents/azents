# SessionDiagnosticEventPage

Forward cursor page of canonical diagnostic event projections.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[SessionDiagnosticEvent]**](SessionDiagnosticEvent.md) |  | 
**next_cursor** | **str** |  | 

## Example

```python
from azentsadminclient.models.session_diagnostic_event_page import SessionDiagnosticEventPage

# TODO update the JSON string below
json = "{}"
# create an instance of SessionDiagnosticEventPage from a JSON string
session_diagnostic_event_page_instance = SessionDiagnosticEventPage.from_json(json)
# print the JSON string representation of the object
print(SessionDiagnosticEventPage.to_json())

# convert the object into a dict
session_diagnostic_event_page_dict = session_diagnostic_event_page_instance.to_dict()
# create an instance of SessionDiagnosticEventPage from a dict
session_diagnostic_event_page_from_dict = SessionDiagnosticEventPage.from_dict(session_diagnostic_event_page_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


