# AutomaticSessionProjectsReplaceRequest

Complete replacement request for automatic-Session Project paths.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** | Revision that must match before replacing the policy | 
**project_paths** | **List[str]** | Ordered existing Project paths; empty clears the policy | 

## Example

```python
from azentspublicclient.models.automatic_session_projects_replace_request import AutomaticSessionProjectsReplaceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AutomaticSessionProjectsReplaceRequest from a JSON string
automatic_session_projects_replace_request_instance = AutomaticSessionProjectsReplaceRequest.from_json(json)
# print the JSON string representation of the object
print(AutomaticSessionProjectsReplaceRequest.to_json())

# convert the object into a dict
automatic_session_projects_replace_request_dict = automatic_session_projects_replace_request_instance.to_dict()
# create an instance of AutomaticSessionProjectsReplaceRequest from a dict
automatic_session_projects_replace_request_from_dict = AutomaticSessionProjectsReplaceRequest.from_dict(automatic_session_projects_replace_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


