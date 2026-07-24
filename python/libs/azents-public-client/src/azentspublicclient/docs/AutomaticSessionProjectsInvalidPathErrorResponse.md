# AutomaticSessionProjectsInvalidPathErrorResponse

FastAPI error envelope for an invalid Project path.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**detail** | [**AutomaticSessionProjectsInvalidPathDetail**](AutomaticSessionProjectsInvalidPathDetail.md) |  | 

## Example

```python
from azentspublicclient.models.automatic_session_projects_invalid_path_error_response import AutomaticSessionProjectsInvalidPathErrorResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AutomaticSessionProjectsInvalidPathErrorResponse from a JSON string
automatic_session_projects_invalid_path_error_response_instance = AutomaticSessionProjectsInvalidPathErrorResponse.from_json(json)
# print the JSON string representation of the object
print(AutomaticSessionProjectsInvalidPathErrorResponse.to_json())

# convert the object into a dict
automatic_session_projects_invalid_path_error_response_dict = automatic_session_projects_invalid_path_error_response_instance.to_dict()
# create an instance of AutomaticSessionProjectsInvalidPathErrorResponse from a dict
automatic_session_projects_invalid_path_error_response_from_dict = AutomaticSessionProjectsInvalidPathErrorResponse.from_dict(automatic_session_projects_invalid_path_error_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


