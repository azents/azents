# SessionWorkspaceProjectRegistrationRequestListResponse

Agent Workspace Project registration request list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[SessionWorkspaceProjectRegistrationRequestResponse]**](SessionWorkspaceProjectRegistrationRequestResponse.md) | Project registration request list |

## Example

```python
from azentspublicclient.models.session_workspace_project_registration_request_list_response import SessionWorkspaceProjectRegistrationRequestListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionWorkspaceProjectRegistrationRequestListResponse from a JSON string
session_workspace_project_registration_request_list_response_instance = SessionWorkspaceProjectRegistrationRequestListResponse.from_json(json)
# print the JSON string representation of the object
print(SessionWorkspaceProjectRegistrationRequestListResponse.to_json())

# convert the object into a dict
session_workspace_project_registration_request_list_response_dict = session_workspace_project_registration_request_list_response_instance.to_dict()
# create an instance of SessionWorkspaceProjectRegistrationRequestListResponse from a dict
session_workspace_project_registration_request_list_response_from_dict = SessionWorkspaceProjectRegistrationRequestListResponse.from_dict(session_workspace_project_registration_request_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
