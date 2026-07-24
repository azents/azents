# AutomaticSessionProjectsConflictErrorResponse

FastAPI error envelope for an automatic Project policy conflict.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**detail** | [**Detail**](Detail.md) |  | 

## Example

```python
from azentspublicclient.models.automatic_session_projects_conflict_error_response import AutomaticSessionProjectsConflictErrorResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AutomaticSessionProjectsConflictErrorResponse from a JSON string
automatic_session_projects_conflict_error_response_instance = AutomaticSessionProjectsConflictErrorResponse.from_json(json)
# print the JSON string representation of the object
print(AutomaticSessionProjectsConflictErrorResponse.to_json())

# convert the object into a dict
automatic_session_projects_conflict_error_response_dict = automatic_session_projects_conflict_error_response_instance.to_dict()
# create an instance of AutomaticSessionProjectsConflictErrorResponse from a dict
automatic_session_projects_conflict_error_response_from_dict = AutomaticSessionProjectsConflictErrorResponse.from_dict(automatic_session_projects_conflict_error_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


