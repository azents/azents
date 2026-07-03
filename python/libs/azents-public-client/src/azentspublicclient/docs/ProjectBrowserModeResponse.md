# ProjectBrowserModeResponse

Workspace browser mode descriptor response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Browser mode ID | 
**label** | **str** | User-facing mode label | 
**default** | **bool** | Whether this is the default browser mode | 
**root_path** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.project_browser_mode_response import ProjectBrowserModeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ProjectBrowserModeResponse from a JSON string
project_browser_mode_response_instance = ProjectBrowserModeResponse.from_json(json)
# print the JSON string representation of the object
print(ProjectBrowserModeResponse.to_json())

# convert the object into a dict
project_browser_mode_response_dict = project_browser_mode_response_instance.to_dict()
# create an instance of ProjectBrowserModeResponse from a dict
project_browser_mode_response_from_dict = ProjectBrowserModeResponse.from_dict(project_browser_mode_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


