# SessionDiagnosticMetadata

Common retained execution metadata; no public Conversation identity.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session_id** | **str** |  | 
**agent_id** | **str** |  | 
**workspace_id** | **str** |  | 
**lifecycle_root_session_id** | **str** |  | 
**status** | [**AgentSessionStatus**](AgentSessionStatus.md) |  | 
**run_state** | [**AgentSessionRunState**](AgentSessionRunState.md) |  | 
**owner_generation** | **int** |  | 
**created_at** | **datetime** |  | 
**started_at** | **datetime** |  | 
**ended_at** | **datetime** |  | 
**archived_at** | **datetime** |  | 
**purge_after** | **datetime** |  | 
**archive_retention_days** | **int** |  | 

## Example

```python
from azentsadminclient.models.session_diagnostic_metadata import SessionDiagnosticMetadata

# TODO update the JSON string below
json = "{}"
# create an instance of SessionDiagnosticMetadata from a JSON string
session_diagnostic_metadata_instance = SessionDiagnosticMetadata.from_json(json)
# print the JSON string representation of the object
print(SessionDiagnosticMetadata.to_json())

# convert the object into a dict
session_diagnostic_metadata_dict = session_diagnostic_metadata_instance.to_dict()
# create an instance of SessionDiagnosticMetadata from a dict
session_diagnostic_metadata_from_dict = SessionDiagnosticMetadata.from_dict(session_diagnostic_metadata_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


