# ProjectBrowserEntrySourceResponse

Project browser entry source metadata response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Entry source type | 
**project_id** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.project_browser_entry_source_response import ProjectBrowserEntrySourceResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ProjectBrowserEntrySourceResponse from a JSON string
project_browser_entry_source_response_instance = ProjectBrowserEntrySourceResponse.from_json(json)
# print the JSON string representation of the object
print(ProjectBrowserEntrySourceResponse.to_json())

# convert the object into a dict
project_browser_entry_source_response_dict = project_browser_entry_source_response_instance.to_dict()
# create an instance of ProjectBrowserEntrySourceResponse from a dict
project_browser_entry_source_response_from_dict = ProjectBrowserEntrySourceResponse.from_dict(project_browser_entry_source_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


