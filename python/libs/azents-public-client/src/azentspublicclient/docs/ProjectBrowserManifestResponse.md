# ProjectBrowserManifestResponse

Backend-owned Project browser manifest response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | Agent ID |
**session_id** | **str** |  | [optional]
**root** | **str** | Agent Workspace root path |
**active_mode** | **str** | Active browser mode |
**modes** | [**List[ProjectBrowserModeResponse]**](ProjectBrowserModeResponse.md) | Available browser modes |
**entries** | [**List[ProjectBrowserEntryResponse]**](ProjectBrowserEntryResponse.md) | Project mode root entries |
**empty_state** | [**ProjectBrowserEmptyStateResponse**](ProjectBrowserEmptyStateResponse.md) |  | [optional]

## Example

```python
from azentspublicclient.models.project_browser_manifest_response import ProjectBrowserManifestResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ProjectBrowserManifestResponse from a JSON string
project_browser_manifest_response_instance = ProjectBrowserManifestResponse.from_json(json)
# print the JSON string representation of the object
print(ProjectBrowserManifestResponse.to_json())

# convert the object into a dict
project_browser_manifest_response_dict = project_browser_manifest_response_instance.to_dict()
# create an instance of ProjectBrowserManifestResponse from a dict
project_browser_manifest_response_from_dict = ProjectBrowserManifestResponse.from_dict(project_browser_manifest_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
