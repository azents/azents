# ProjectBrowserEmptyStateResponse

Project mode empty-state response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**title** | **str** | Empty-state title | 
**description** | **str** | Empty-state explanatory text | 

## Example

```python
from azentspublicclient.models.project_browser_empty_state_response import ProjectBrowserEmptyStateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ProjectBrowserEmptyStateResponse from a JSON string
project_browser_empty_state_response_instance = ProjectBrowserEmptyStateResponse.from_json(json)
# print the JSON string representation of the object
print(ProjectBrowserEmptyStateResponse.to_json())

# convert the object into a dict
project_browser_empty_state_response_dict = project_browser_empty_state_response_instance.to_dict()
# create an instance of ProjectBrowserEmptyStateResponse from a dict
project_browser_empty_state_response_from_dict = ProjectBrowserEmptyStateResponse.from_dict(project_browser_empty_state_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


