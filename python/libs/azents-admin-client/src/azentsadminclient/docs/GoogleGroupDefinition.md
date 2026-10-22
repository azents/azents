# GoogleGroupDefinition


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**group** | [**GoogleToolGroup**](GoogleToolGroup.md) |  | 
**service** | [**GoogleService**](GoogleService.md) |  | 
**operations** | [**List[GoogleWorkspaceOperation]**](GoogleWorkspaceOperation.md) |  | 
**request_scopes** | **List[str]** |  | 

## Example

```python
from azentsadminclient.models.google_group_definition import GoogleGroupDefinition

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleGroupDefinition from a JSON string
google_group_definition_instance = GoogleGroupDefinition.from_json(json)
# print the JSON string representation of the object
print(GoogleGroupDefinition.to_json())

# convert the object into a dict
google_group_definition_dict = google_group_definition_instance.to_dict()
# create an instance of GoogleGroupDefinition from a dict
google_group_definition_from_dict = GoogleGroupDefinition.from_dict(google_group_definition_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


