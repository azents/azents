# AutomaticSessionProjectsResponse

Ordered Agent automatic-Session Project policy response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**revision** | **int** | Optimistic policy revision | 
**project_paths** | **List[str]** | Ordered normalized existing Project paths | 
**updated_at** | **datetime** | Last policy update time | 

## Example

```python
from azentspublicclient.models.automatic_session_projects_response import AutomaticSessionProjectsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AutomaticSessionProjectsResponse from a JSON string
automatic_session_projects_response_instance = AutomaticSessionProjectsResponse.from_json(json)
# print the JSON string representation of the object
print(AutomaticSessionProjectsResponse.to_json())

# convert the object into a dict
automatic_session_projects_response_dict = automatic_session_projects_response_instance.to_dict()
# create an instance of AutomaticSessionProjectsResponse from a dict
automatic_session_projects_response_from_dict = AutomaticSessionProjectsResponse.from_dict(automatic_session_projects_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


