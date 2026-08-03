# CreateSessionWorkingFolderAction

Materialize the current Session context's owned working folder.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'create_session_working_folder']

## Example

```python
from azentspublicclient.models.create_session_working_folder_action import CreateSessionWorkingFolderAction

# TODO update the JSON string below
json = "{}"
# create an instance of CreateSessionWorkingFolderAction from a JSON string
create_session_working_folder_action_instance = CreateSessionWorkingFolderAction.from_json(json)
# print the JSON string representation of the object
print(CreateSessionWorkingFolderAction.to_json())

# convert the object into a dict
create_session_working_folder_action_dict = create_session_working_folder_action_instance.to_dict()
# create an instance of CreateSessionWorkingFolderAction from a dict
create_session_working_folder_action_from_dict = CreateSessionWorkingFolderAction.from_dict(create_session_working_folder_action_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


