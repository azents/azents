# AutomaticSessionProjectsMessageErrorResponse

FastAPI error envelope containing a user-facing message.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**detail** | **str** |  | 

## Example

```python
from azentspublicclient.models.automatic_session_projects_message_error_response import AutomaticSessionProjectsMessageErrorResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AutomaticSessionProjectsMessageErrorResponse from a JSON string
automatic_session_projects_message_error_response_instance = AutomaticSessionProjectsMessageErrorResponse.from_json(json)
# print the JSON string representation of the object
print(AutomaticSessionProjectsMessageErrorResponse.to_json())

# convert the object into a dict
automatic_session_projects_message_error_response_dict = automatic_session_projects_message_error_response_instance.to_dict()
# create an instance of AutomaticSessionProjectsMessageErrorResponse from a dict
automatic_session_projects_message_error_response_from_dict = AutomaticSessionProjectsMessageErrorResponse.from_dict(automatic_session_projects_message_error_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


