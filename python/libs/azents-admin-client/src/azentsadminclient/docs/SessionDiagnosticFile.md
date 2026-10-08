# SessionDiagnosticFile

Bounded current durable file content; not file history or restoration.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**path** | **str** |  | 
**writable** | **bool** |  | 
**content** | **str** |  | 
**next_offset** | **int** |  | 

## Example

```python
from azentsadminclient.models.session_diagnostic_file import SessionDiagnosticFile

# TODO update the JSON string below
json = "{}"
# create an instance of SessionDiagnosticFile from a JSON string
session_diagnostic_file_instance = SessionDiagnosticFile.from_json(json)
# print the JSON string representation of the object
print(SessionDiagnosticFile.to_json())

# convert the object into a dict
session_diagnostic_file_dict = session_diagnostic_file_instance.to_dict()
# create an instance of SessionDiagnosticFile from a dict
session_diagnostic_file_from_dict = SessionDiagnosticFile.from_dict(session_diagnostic_file_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


