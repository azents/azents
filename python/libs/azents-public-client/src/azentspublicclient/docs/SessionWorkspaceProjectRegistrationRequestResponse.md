# SessionWorkspaceProjectRegistrationRequestResponse

Agent Workspace Project registration request response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Request ID | 
**path** | **str** | Requested Project path | 
**reason** | **str** | Request reason provided by the Agent | 
**status** | **str** | Request status | 
**project_id** | **str** |  | [optional] 
**created_at** | **datetime** | Created time | 
**updated_at** | **datetime** | Updated time | 

## Example

```python
from azentspublicclient.models.session_workspace_project_registration_request_response import SessionWorkspaceProjectRegistrationRequestResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionWorkspaceProjectRegistrationRequestResponse from a JSON string
session_workspace_project_registration_request_response_instance = SessionWorkspaceProjectRegistrationRequestResponse.from_json(json)
# print the JSON string representation of the object
print(SessionWorkspaceProjectRegistrationRequestResponse.to_json())

# convert the object into a dict
session_workspace_project_registration_request_response_dict = session_workspace_project_registration_request_response_instance.to_dict()
# create an instance of SessionWorkspaceProjectRegistrationRequestResponse from a dict
session_workspace_project_registration_request_response_from_dict = SessionWorkspaceProjectRegistrationRequestResponse.from_dict(session_workspace_project_registration_request_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


