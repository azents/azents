# ProjectBrowserEntryCapabilitiesResponse

Backend-provided Project root action policy response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**open** | **bool** | Whether the entry can be opened in the browser |
**remove_project** | **bool** | Whether the registry Project row can be removed |
**filesystem_delete** | **bool** | Whether filesystem delete is allowed for this entry |
**filesystem_move** | **bool** | Whether filesystem move is allowed for this entry |
**filesystem_rename** | **bool** | Whether filesystem rename is allowed for this entry |

## Example

```python
from azentspublicclient.models.project_browser_entry_capabilities_response import ProjectBrowserEntryCapabilitiesResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ProjectBrowserEntryCapabilitiesResponse from a JSON string
project_browser_entry_capabilities_response_instance = ProjectBrowserEntryCapabilitiesResponse.from_json(json)
# print the JSON string representation of the object
print(ProjectBrowserEntryCapabilitiesResponse.to_json())

# convert the object into a dict
project_browser_entry_capabilities_response_dict = project_browser_entry_capabilities_response_instance.to_dict()
# create an instance of ProjectBrowserEntryCapabilitiesResponse from a dict
project_browser_entry_capabilities_response_from_dict = ProjectBrowserEntryCapabilitiesResponse.from_dict(project_browser_entry_capabilities_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
