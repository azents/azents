# GitRefEntryResponse

Git ref entry response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Display ref name | 
**ref** | **str** | Full Git ref | 
**type** | **str** | Git ref type | 
**target** | **str** | Target commit | 
**default** | **bool** | Whether this is the default ref | 

## Example

```python
from azentspublicclient.models.git_ref_entry_response import GitRefEntryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GitRefEntryResponse from a JSON string
git_ref_entry_response_instance = GitRefEntryResponse.from_json(json)
# print the JSON string representation of the object
print(GitRefEntryResponse.to_json())

# convert the object into a dict
git_ref_entry_response_dict = git_ref_entry_response_instance.to_dict()
# create an instance of GitRefEntryResponse from a dict
git_ref_entry_response_from_dict = GitRefEntryResponse.from_dict(git_ref_entry_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


