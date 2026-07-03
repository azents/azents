# ProjectBrowserEntryStatusResponse

Project browser filesystem status projection response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**value** | **str** | Stored filesystem status projection |
**detail** | **str** |  | [optional]
**checked_at** | **datetime** |  | [optional]
**stale** | **bool** | Whether a background refresh is recommended |

## Example

```python
from azentspublicclient.models.project_browser_entry_status_response import ProjectBrowserEntryStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ProjectBrowserEntryStatusResponse from a JSON string
project_browser_entry_status_response_instance = ProjectBrowserEntryStatusResponse.from_json(json)
# print the JSON string representation of the object
print(ProjectBrowserEntryStatusResponse.to_json())

# convert the object into a dict
project_browser_entry_status_response_dict = project_browser_entry_status_response_instance.to_dict()
# create an instance of ProjectBrowserEntryStatusResponse from a dict
project_browser_entry_status_response_from_dict = ProjectBrowserEntryStatusResponse.from_dict(project_browser_entry_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
