# ProjectBrowserEntryResponse

Project root entry response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Project root display name |
**path** | **str** | Agent Workspace absolute path |
**kind** | **str** | Entry kind |
**source** | [**ProjectBrowserEntrySourceResponse**](ProjectBrowserEntrySourceResponse.md) | Entry source |
**status** | [**ProjectBrowserEntryStatusResponse**](ProjectBrowserEntryStatusResponse.md) | Filesystem status projection |
**capabilities** | [**ProjectBrowserEntryCapabilitiesResponse**](ProjectBrowserEntryCapabilitiesResponse.md) | Backend-provided entry action policy |

## Example

```python
from azentspublicclient.models.project_browser_entry_response import ProjectBrowserEntryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ProjectBrowserEntryResponse from a JSON string
project_browser_entry_response_instance = ProjectBrowserEntryResponse.from_json(json)
# print the JSON string representation of the object
print(ProjectBrowserEntryResponse.to_json())

# convert the object into a dict
project_browser_entry_response_dict = project_browser_entry_response_instance.to_dict()
# create an instance of ProjectBrowserEntryResponse from a dict
project_browser_entry_response_from_dict = ProjectBrowserEntryResponse.from_dict(project_browser_entry_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
