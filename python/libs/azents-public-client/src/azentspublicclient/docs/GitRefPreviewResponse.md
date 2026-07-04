# GitRefPreviewResponse

Git ref preview response for a source Project.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**refs** | [**List[GitRefEntryResponse]**](GitRefEntryResponse.md) | Available Git refs | 
**default_branch** | **str** |  | 
**head_commit** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_ref_preview_response import GitRefPreviewResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GitRefPreviewResponse from a JSON string
git_ref_preview_response_instance = GitRefPreviewResponse.from_json(json)
# print the JSON string representation of the object
print(GitRefPreviewResponse.to_json())

# convert the object into a dict
git_ref_preview_response_dict = git_ref_preview_response_instance.to_dict()
# create an instance of GitRefPreviewResponse from a dict
git_ref_preview_response_from_dict = GitRefPreviewResponse.from_dict(git_ref_preview_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


