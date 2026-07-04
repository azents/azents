# ProjectBrowserManifestPreviewRequest

Pre-session Project browser manifest preview request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**project_paths** | **List[str]** | Exact Project paths to preview before session creation | 

## Example

```python
from azentspublicclient.models.project_browser_manifest_preview_request import ProjectBrowserManifestPreviewRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ProjectBrowserManifestPreviewRequest from a JSON string
project_browser_manifest_preview_request_instance = ProjectBrowserManifestPreviewRequest.from_json(json)
# print the JSON string representation of the object
print(ProjectBrowserManifestPreviewRequest.to_json())

# convert the object into a dict
project_browser_manifest_preview_request_dict = project_browser_manifest_preview_request_instance.to_dict()
# create an instance of ProjectBrowserManifestPreviewRequest from a dict
project_browser_manifest_preview_request_from_dict = ProjectBrowserManifestPreviewRequest.from_dict(project_browser_manifest_preview_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


